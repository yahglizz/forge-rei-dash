-- Notify-only: GHL stops being a two-way inbox and becomes a notification surface.
--
-- Why this changed. Under the OutboundMessage design an owner reply typed in GHL was
-- delivered as a real SMS by LeadConnector *and* mirrored into the app thread, so the
-- family received the same reply twice. The owner replies from the app instead; GHL
-- (and now email) only tells them there is something to reply to.
--
-- So the GHL -> app direction is gone: no webhook, no signature verification, no
-- inbound writes into public.messages. Everything that existed only to serve that
-- direction is dropped here. messages.ghl_message_id stays — it costs nothing and it
-- keeps the loop guard in place if the inbound path is ever revived.

-- ---------------------------------------------------------------------------
-- 1. Drop what only the inbound webhook used
-- ---------------------------------------------------------------------------
drop table if exists public.ghl_processed;   -- webhook replay claims
drop table if exists public.ghl_user_links;  -- GHL user -> app profile attribution

-- Where an owner reply from GHL would have landed. Nothing replies from GHL now.
alter table public.ghl_contact_links drop column if exists reply_thread_id;

-- ---------------------------------------------------------------------------
-- 2. Email as a second, independent notification channel
-- ---------------------------------------------------------------------------
-- Its own status column rather than a second table: the two channels share a row but
-- settle separately, so a GHL outage cannot swallow the email and vice versa.
alter table public.ghl_outbox
  add column if not exists email_status text not null default 'skipped',
  add column if not exists email_error  text;

alter table public.ghl_outbox drop constraint if exists ghl_outbox_email_status_check;
alter table public.ghl_outbox add constraint ghl_outbox_email_status_check
  check (email_status in ('pending','sent','skipped','failed'));

create index if not exists ghl_outbox_email_pending_idx
  on public.ghl_outbox (created_at) where email_status = 'pending';

comment on column public.ghl_outbox.email_status is
  'Email notification channel, independent of status (the GHL channel). Defaults to skipped: only items the owner actually needs to act on are set pending at enqueue time.';

-- ---------------------------------------------------------------------------
-- 3. Labels
-- ---------------------------------------------------------------------------
-- One place, so a notification says what it is in every channel — the GHL inbox row,
-- the email subject, and the push preview all read the same prefix.
create or replace function public.ghl_label(p_kind text, p_direction text)
returns text language sql immutable set search_path = public as $$
  select case
    when p_kind = 'incident'            then '[INCIDENT REPORT]'
    when p_kind = 'parent_report'       then '[PARENT REPORT]'
    when p_kind = 'parent_report_reply'
      then case when p_direction = 'inbound' then '[PARENT REPORT REPLY]'
                else '[CENTER REPORT REPLY]' end
    when p_kind = 'message'
      then case when p_direction = 'inbound' then '[PARENT MESSAGE]'
                else '[CENTER REPLY]' end
    else '[NOTIFICATION]'
  end;
$$;

-- ---------------------------------------------------------------------------
-- 4. Enqueue — labels the body and decides whether email fires
-- ---------------------------------------------------------------------------
create or replace function public.ghl_enqueue(
  p_location_id uuid, p_profile_id uuid, p_kind text,
  p_source_id uuid, p_body text, p_direction text
) returns void language plpgsql security definer set search_path = public as $$
declare
  labelled text;
  email_st text;
begin
  if p_profile_id is null or p_body is null or btrim(p_body) = '' then return; end if;
  if not public.ghl_location_enabled(p_location_id) then return; end if;

  labelled := public.ghl_label(p_kind, p_direction) || ' ' || left(p_body, 3800);

  -- The GHL thread is a notification surface, not an inbox to answer from: a reply
  -- typed there is delivered by LeadConnector as a real SMS, which is exactly the
  -- double-delivery this design exists to avoid. Say so where the owner will read it.
  if p_direction = 'inbound' then
    labelled := labelled || E'\n\n(Reply in the app — a reply typed here sends an SMS.)';
  end if;

  -- Email only for things needing the owner: anything the family sent, plus incidents,
  -- which a staff member files but the owner still has to know about immediately.
  -- The center's own replies would just be the owner mailing themselves.
  email_st := case when p_direction = 'inbound' or p_kind = 'incident'
                   then 'pending' else 'skipped' end;

  insert into public.ghl_outbox (location_id, profile_id, kind, source_id, body,
                                 direction, email_status)
  values (p_location_id, p_profile_id, p_kind, p_source_id, labelled,
          p_direction, email_st)
  on conflict (kind, source_id, profile_id) do nothing;
end $$;

-- ---------------------------------------------------------------------------
-- 5. Triggers — drop the ad-hoc prefixes now that ghl_enqueue labels centrally,
--    and stop tracking a reply thread nothing replies into.
-- ---------------------------------------------------------------------------
create or replace function public.ghl_enqueue_message()
returns trigger language plpgsql security definer set search_path = public as $$
declare
  loc        uuid;
  sender     record;
  parent_row record;
begin
  -- Belt and braces: nothing writes messages from GHL any more, but if the inbound
  -- path ever returns this is still what stops a reply bouncing back out.
  if new.ghl_message_id is not null then return new; end if;

  select location_id into loc from public.message_threads where id = new.thread_id;
  if loc is null or not public.ghl_location_enabled(loc) then return new; end if;

  select id, role, display_name into sender from public.profiles where id = new.sender_id;

  for parent_row in
    select p.id
    from public.thread_participants tp
    join public.profiles p on p.id = tp.profile_id
    where tp.thread_id = new.thread_id and p.role = 'parent' and p.active
  loop
    if sender.id is not null and sender.id = parent_row.id then
      perform public.ghl_enqueue(loc, parent_row.id, 'message', new.id, new.body, 'inbound');
    else
      -- GHL has a single business identity, so the author's name has to ride in the
      -- body or the owner cannot tell which staff member answered.
      perform public.ghl_enqueue(loc, parent_row.id, 'message', new.id,
                                 coalesce(sender.display_name, 'Center') || ': ' || new.body,
                                 'outbound');
    end if;
  end loop;

  return new;
end $$;

create or replace function public.ghl_enqueue_incident()
returns trigger language plpgsql security definer set search_path = public as $$
declare
  child_row  record;
  parent_row record;
  summary    text;
begin
  select first_name, last_name into child_row from public.children where id = new.child_id;

  summary := coalesce(child_row.first_name, '') || ' ' || coalesce(child_row.last_name, '')
    || E'\n' || 'When: '     || to_char(new.occurred_at, 'YYYY-MM-DD HH24:MI')
    || E'\n' || 'Where: '    || new.location_detail
    || E'\n' || 'Severity: ' || new.severity::text
    || E'\n' || 'What happened: ' || new.description
    || E'\n' || 'Action taken: '  || new.action_taken;

  for parent_row in select * from public.ghl_child_parents(new.child_id) loop
    perform public.ghl_enqueue(parent_row.location_id, parent_row.profile_id,
                               'incident', new.id, summary, 'outbound');
  end loop;
  return new;
end $$;

create or replace function public.ghl_enqueue_parent_report()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  perform public.ghl_enqueue(new.location_id, new.author_id, 'parent_report', new.id,
                             new.subject || E'\n\n' || new.body, 'inbound');
  return new;
end $$;

-- ---------------------------------------------------------------------------
-- 6. Claim — now covers both channels
-- ---------------------------------------------------------------------------
-- A row can be done on one channel and still owed on the other (GHL sent, email
-- failed), so the claim looks at both. status is only moved to 'sending' when it is
-- still live; a row already 'sent' to GHL keeps that terminal state while its email
-- gets another go.
create or replace function public.ghl_claim_outbox(p_limit int default 25)
returns setof public.ghl_outbox
language plpgsql security definer set search_path = public as $$
begin
  -- Park anything past its retries. The stale-'sending' case is included: without it
  -- a row stuck mid-flight is reclaimed forever and never gives up.
  update public.ghl_outbox
     set status = 'failed', updated_at = now()
   where attempts >= 5
     and (status = 'pending'
          or (status = 'sending' and updated_at < now() - interval '5 minutes'));

  update public.ghl_outbox
     set email_status = 'failed', updated_at = now()
   where attempts >= 5 and email_status = 'pending';

  return query
  update public.ghl_outbox o
     set status = case when o.status in ('pending','sending') then 'sending' else o.status end,
         attempts = o.attempts + 1,
         updated_at = now()
   where o.id in (
     select id from public.ghl_outbox
      where attempts < 5
        and (status = 'pending'
             or email_status = 'pending'
             -- Killed mid-flight (function timeout, deploy). Fair game again after 5m.
             or (status = 'sending' and updated_at < now() - interval '5 minutes'))
      order by created_at
      limit p_limit
      for update skip locked
   )
  returning o.*;
end $$;

revoke all on function public.ghl_claim_outbox(int) from public, anon, authenticated;
grant execute on function public.ghl_claim_outbox(int) to service_role;
revoke all on function public.ghl_enqueue(uuid, uuid, text, uuid, text, text) from public, anon, authenticated;
revoke all on function public.ghl_label(text, text) from public, anon, authenticated;

-- ---------------------------------------------------------------------------
-- 7. Requeue both channels
-- ---------------------------------------------------------------------------
-- Adding a missing phone number releases the GHL backlog; the email backlog for the
-- same family is released with it, or the owner silently never hears about those items.
create or replace function public.ghl_retry_skipped(p_profile_id uuid)
returns integer language plpgsql security definer set search_path = public as $$
declare n integer;
begin
  if public.my_role() <> 'admin' then
    raise exception 'only an admin can requeue GHL items';
  end if;

  update public.ghl_outbox o
     set status = case when o.status = 'skipped' then 'pending' else o.status end,
         email_status = case
           when o.email_status = 'failed'
             and (o.direction = 'inbound' or o.kind = 'incident') then 'pending'
           else o.email_status end,
         attempts = 0, last_error = null, email_error = null, updated_at = now()
   where o.profile_id = p_profile_id
     and o.location_id = public.my_location()
     and (o.status = 'skipped' or o.email_status = 'failed');

  get diagnostics n = row_count;
  return n;
end $$;

-- ---------------------------------------------------------------------------
-- 8. Dispatcher — wake for either channel
-- ---------------------------------------------------------------------------
-- The old guard counted only status='pending'. A row whose GHL copy has already sent
-- but whose email failed sits at status='sent', email_status='pending' — invisible to
-- that count, so the drain was never poked and the email silently never retried.
-- The stale-'sending' case had the same hole: nothing re-dispatched a stuck row unless
-- an unrelated message happened to arrive behind it.
create or replace function public.dispatch_ghl_outbox()
returns integer language plpgsql security definer set search_path = public as $$
declare
  fn_url   text;
  secret   text;
  anon_key text;
  pending  integer;
begin
  select count(*) into pending from public.ghl_outbox
   where status in ('pending','sending') or email_status = 'pending';
  if pending = 0 then return 0; end if;

  select decrypted_secret into fn_url   from vault.decrypted_secrets where name = 'ghl_push_fn_url';
  select decrypted_secret into secret   from vault.decrypted_secrets where name = 'ghl_cron_secret';
  select decrypted_secret into anon_key from vault.decrypted_secrets where name = 'ghl_anon_key';

  if fn_url is null or secret is null or anon_key is null then
    raise warning 'dispatch_ghl_outbox: vault secrets missing — % rows left pending', pending;
    return 0;
  end if;

  perform net.http_post(
    url := fn_url,
    headers := jsonb_build_object(
      'Content-Type',  'application/json',
      'Authorization', 'Bearer ' || anon_key,
      'x-cron-secret', secret
    ),
    body := '{}'::jsonb
  );
  return pending;
end $$;

revoke all on function public.dispatch_ghl_outbox() from public, anon, authenticated;
