-- Two-way bridge between the app's family messaging and the GHL Conversations inbox.
--
-- Shape, and why:
--   app -> GHL   a trigger drops a row in ghl_outbox; pg_cron pokes the ghl-push
--                edge function once a minute, which drains it. The trigger does NOT
--                call out over the network itself — an http_post inside the insert
--                transaction means a GHL outage becomes a failed message send for a
--                parent, and a family's message must never depend on a CRM being up.
--   GHL -> app   the ghl-outbound edge function receives the Conversation Provider
--                webhook and writes the owner's reply straight into messages.
--
-- Loop prevention is messages.ghl_message_id: a row that came FROM GHL carries the
-- GHL message id, and the enqueue trigger ignores any row where it is set. The unique
-- index on it doubles as webhook-redelivery idempotency, which GHL will do on timeout.
--
-- Nothing here syncs anything until a location is added to ghl_config. Fails closed
-- on purpose: an empty config is an inert install, not a live one.

-- ---------------------------------------------------------------------------
-- 1. Loop prevention / idempotency marker
-- ---------------------------------------------------------------------------
alter table public.messages add column if not exists ghl_message_id text;
comment on column public.messages.ghl_message_id is
  'GHL message id when this row was written BY the ghl-outbound webhook. Non-null means "came from GHL" — the enqueue trigger skips it so a reply cannot bounce back.';

create unique index if not exists messages_ghl_message_id_key
  on public.messages (ghl_message_id) where ghl_message_id is not null;

-- ---------------------------------------------------------------------------
-- 2. Config — the kill switch and the allowlist
-- ---------------------------------------------------------------------------
create table if not exists public.ghl_config (
  location_id uuid primary key references public.locations(id) on delete cascade,
  enabled     boolean not null default true,
  created_at  timestamptz not null default now()
);
comment on table public.ghl_config is
  'Which app locations mirror into GHL. No row = no sync. Set enabled=false to stop the bridge without dropping the links.';

-- ---------------------------------------------------------------------------
-- 3. OAuth token for the marketplace app
-- ---------------------------------------------------------------------------
-- Single row. RLS on with NO policies: unreachable from anon and authenticated,
-- readable only by service_role (which bypasses RLS) inside the edge functions.
create table if not exists public.ghl_oauth (
  id            smallint primary key default 1 check (id = 1),
  access_token  text not null,
  refresh_token text not null,
  expires_at    timestamptz not null,
  location_id   text not null,
  updated_at    timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- 4. Family <-> GHL contact links
-- ---------------------------------------------------------------------------
create table if not exists public.ghl_contact_links (
  profile_id          uuid primary key references public.profiles(id) on delete cascade,
  ghl_contact_id      text not null unique,
  ghl_conversation_id text,
  -- Where an owner reply from GHL lands. GHL has one conversation per contact, but
  -- the app can have several threads per parent, so the bridge picks the thread the
  -- most recent push came from rather than guessing.
  reply_thread_id     uuid references public.message_threads(id) on delete set null,
  linked_at           timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);

-- GHL user (whoever typed the reply) -> app profile, so the reply is attributed to a
-- real person in the thread instead of a generic "center" account.
create table if not exists public.ghl_user_links (
  ghl_user_id text primary key,
  profile_id  uuid not null references public.profiles(id) on delete cascade
);

-- ---------------------------------------------------------------------------
-- 5. Outbox
-- ---------------------------------------------------------------------------
create table if not exists public.ghl_outbox (
  id             bigserial primary key,
  location_id    uuid not null references public.locations(id) on delete cascade,
  -- Whose GHL conversation this belongs in: always the PARENT, never the staff author.
  profile_id     uuid not null references public.profiles(id) on delete cascade,
  kind           text not null check (kind in ('message','incident','parent_report','parent_report_reply')),
  source_id      uuid not null,
  body           text not null,
  direction      text not null check (direction in ('inbound','outbound')),
  status         text not null default 'pending'
                 check (status in ('pending','sent','skipped','failed')),
  attempts       int  not null default 0,
  last_error     text,
  ghl_message_id text,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

-- One row per (kind, source, parent). Makes the whole pipeline replay-safe: a retried
-- dispatch or a re-run trigger cannot double-post the same message into GHL.
create unique index if not exists ghl_outbox_source_key
  on public.ghl_outbox (kind, source_id, profile_id);

create index if not exists ghl_outbox_pending_idx
  on public.ghl_outbox (created_at) where status = 'pending';

-- ---------------------------------------------------------------------------
-- 6. Enqueue helpers
-- ---------------------------------------------------------------------------
create or replace function public.ghl_location_enabled(p_location_id uuid)
returns boolean language sql stable security definer set search_path = public as $$
  select exists (select 1 from public.ghl_config where location_id = p_location_id and enabled);
$$;

create or replace function public.ghl_enqueue(
  p_location_id uuid, p_profile_id uuid, p_kind text,
  p_source_id uuid, p_body text, p_direction text
) returns void language plpgsql security definer set search_path = public as $$
begin
  if p_profile_id is null or p_body is null or btrim(p_body) = '' then return; end if;
  if not public.ghl_location_enabled(p_location_id) then return; end if;

  insert into public.ghl_outbox (location_id, profile_id, kind, source_id, body, direction)
  values (p_location_id, p_profile_id, p_kind, p_source_id, left(p_body, 4000), p_direction)
  on conflict (kind, source_id, profile_id) do nothing;
end $$;

-- The parent guardians who should see a given child's activity in GHL.
create or replace function public.ghl_child_parents(p_child_id uuid)
returns table (profile_id uuid, location_id uuid)
language sql stable security definer set search_path = public as $$
  select p.id, p.location_id
  from public.guardian_children gc
  join public.guardians g  on g.id = gc.guardian_id
  join public.profiles  p  on p.id = g.profile_id
  where gc.child_id = p_child_id and p.role = 'parent' and p.active;
$$;

-- ---------------------------------------------------------------------------
-- 7. Triggers
-- ---------------------------------------------------------------------------

-- messages: push BOTH sides of the conversation. A GHL inbox showing only the
-- parent's half would have the owner answering things staff already answered.
-- direction distinguishes them: the family's own words arrive as inbound (left
-- side in GHL), the center's as outbound (right side), which is what makes the
-- GHL thread read as a real transcript.
create or replace function public.ghl_enqueue_message()
returns trigger language plpgsql security definer set search_path = public as $$
declare
  loc        uuid;
  sender     record;
  parent_row record;
  label      text;
begin
  -- Written by the ghl-outbound webhook: it is already in GHL. Do not send it back.
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
      -- The family's own message.
      perform public.ghl_enqueue(loc, parent_row.id, 'message', new.id, new.body, 'inbound');
    else
      -- Someone at the center. GHL has a single business identity, so the author's
      -- name has to ride in the body or the owner cannot tell staff apart.
      label := coalesce(sender.display_name, 'Center');
      perform public.ghl_enqueue(loc, parent_row.id, 'message', new.id,
                                 label || ': ' || new.body, 'outbound');
    end if;

    -- Remember where a reply should land.
    update public.ghl_contact_links
       set reply_thread_id = new.thread_id, updated_at = now()
     where profile_id = parent_row.id;
  end loop;

  return new;
end $$;

drop trigger if exists ghl_message_sync on public.messages;
create trigger ghl_message_sync after insert on public.messages
for each row execute function public.ghl_enqueue_message();

-- incident_reports: always from the center to the family.
create or replace function public.ghl_enqueue_incident()
returns trigger language plpgsql security definer set search_path = public as $$
declare
  child_row  record;
  parent_row record;
  summary    text;
begin
  select first_name, last_name into child_row from public.children where id = new.child_id;

  summary := 'INCIDENT REPORT — ' || coalesce(child_row.first_name, '') || ' ' || coalesce(child_row.last_name, '')
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

drop trigger if exists ghl_incident_sync on public.incident_reports;
create trigger ghl_incident_sync after insert on public.incident_reports
for each row execute function public.ghl_enqueue_incident();

-- parent_reports: the family's private line to the owner.
create or replace function public.ghl_enqueue_parent_report()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  perform public.ghl_enqueue(new.location_id, new.author_id, 'parent_report', new.id,
                             'REPORT — ' || new.subject || E'\n\n' || new.body, 'inbound');
  return new;
end $$;

drop trigger if exists ghl_parent_report_sync on public.parent_reports;
create trigger ghl_parent_report_sync after insert on public.parent_reports
for each row execute function public.ghl_enqueue_parent_report();

-- parent_report_replies: either side may write these, so the direction follows the author.
create or replace function public.ghl_enqueue_parent_report_reply()
returns trigger language plpgsql security definer set search_path = public as $$
declare
  rep    record;
  author record;
begin
  select location_id, author_id, subject into rep from public.parent_reports where id = new.report_id;
  if rep.author_id is null then return new; end if;

  select display_name, role into author from public.profiles where id = new.author_id;

  if new.author_id = rep.author_id then
    perform public.ghl_enqueue(rep.location_id, rep.author_id, 'parent_report_reply', new.id,
                               're: ' || rep.subject || E'\n\n' || new.body, 'inbound');
  else
    perform public.ghl_enqueue(rep.location_id, rep.author_id, 'parent_report_reply', new.id,
                               coalesce(author.display_name, 'Center') || ' re: ' || rep.subject
                               || E'\n\n' || new.body, 'outbound');
  end if;
  return new;
end $$;

drop trigger if exists ghl_parent_report_reply_sync on public.parent_report_replies;
create trigger ghl_parent_report_reply_sync after insert on public.parent_report_replies
for each row execute function public.ghl_enqueue_parent_report_reply();

-- ---------------------------------------------------------------------------
-- 8. Dispatcher — same vault + pg_net shape as dispatch_signin_sheets
-- ---------------------------------------------------------------------------
-- Secrets live in vault, not here — this file is committed. Create them once:
--   select vault.create_secret('https://<ref>.supabase.co/functions/v1/ghl-push', 'ghl_push_fn_url');
--   select vault.create_secret(encode(gen_random_bytes(32), 'hex'), 'ghl_cron_secret');
--   select vault.create_secret('<publishable/anon key>', 'ghl_anon_key');
-- ghl_cron_secret must ALSO be set as GHL_CRON_SECRET on the edge function.
create or replace function public.dispatch_ghl_outbox()
returns integer language plpgsql security definer set search_path = public as $$
declare
  fn_url   text;
  secret   text;
  anon_key text;
  pending  integer;
begin
  select count(*) into pending from public.ghl_outbox where status = 'pending';
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
revoke all on function public.ghl_enqueue(uuid, uuid, text, uuid, text, text) from public, anon, authenticated;
revoke all on function public.ghl_location_enabled(uuid) from public, anon, authenticated;
revoke all on function public.ghl_child_parents(uuid) from public, anon, authenticated;

select cron.unschedule('ghl-outbox-drain')
where exists (select 1 from cron.job where jobname = 'ghl-outbox-drain');

select cron.schedule('ghl-outbox-drain', '* * * * *', $$select public.dispatch_ghl_outbox()$$);

-- ---------------------------------------------------------------------------
-- 9. RLS
-- ---------------------------------------------------------------------------
alter table public.ghl_config        enable row level security;
alter table public.ghl_oauth         enable row level security;
alter table public.ghl_contact_links enable row level security;
alter table public.ghl_user_links    enable row level security;
alter table public.ghl_outbox        enable row level security;

-- ghl_oauth gets NO policy at all. Tokens are service_role-only by construction.

-- Admins can see the bridge's state for their own location — this is what backs the
-- "families not linked yet" list, which is the only reason a human needs to read it.
drop policy if exists "admin reads ghl config" on public.ghl_config;
create policy "admin reads ghl config" on public.ghl_config
  for select using (public.my_role() = 'admin' and location_id = public.my_location());

drop policy if exists "admin reads ghl links" on public.ghl_contact_links;
create policy "admin reads ghl links" on public.ghl_contact_links
  for select using (
    public.my_role() = 'admin'
    and exists (select 1 from public.profiles p
                 where p.id = profile_id and p.location_id = public.my_location())
  );

drop policy if exists "admin reads ghl outbox" on public.ghl_outbox;
create policy "admin reads ghl outbox" on public.ghl_outbox
  for select using (public.my_role() = 'admin' and location_id = public.my_location());

-- Families that cannot sync yet because no phone number is on file. The owner-facing
-- "go add a number" list reads from here.
create or replace view public.ghl_unlinked_families
with (security_invoker = true) as
  select p.id as profile_id, p.location_id, p.display_name, p.phone,
         count(o.id) filter (where o.status = 'skipped') as waiting_items,
         max(o.created_at) as last_attempt
  from public.profiles p
  join public.ghl_outbox o on o.profile_id = p.id
  left join public.ghl_contact_links l on l.profile_id = p.id
  where p.role = 'parent' and l.profile_id is null
  group by p.id, p.location_id, p.display_name, p.phone;

comment on view public.ghl_unlinked_families is
  'Parents with queued GHL items but no contact link — almost always a missing phone number. security_invoker means it obeys the admin-only policy on ghl_outbox.';
