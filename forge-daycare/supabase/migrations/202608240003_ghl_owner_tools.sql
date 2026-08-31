-- Replay guard for the inbound webhook + the owner-facing requeue action.
--
-- ghl_processed: GHL redelivers on timeout, and a signed body can be replayed
-- verbatim because the payload carries no timestamp. On the app path a replay is
-- caught by the unique index on messages.ghl_message_id, but on the Twilio relay path
-- it would text a family twice. Claimed BEFORE either side acts, so both are
-- exactly-once; the claim is released again if the work throws.
create table if not exists public.ghl_processed (
  ghl_message_id text primary key,
  routed         text not null check (routed in ('app','relay')),
  created_at     timestamptz not null default now()
);

alter table public.ghl_processed enable row level security;

comment on table public.ghl_processed is
  'Every GHL outbound-webhook message id we have already acted on. Insert-first; a unique violation means redelivery or replay, and the request is a no-op.';

-- Adding the missing phone number is only half the fix: everything already parked as
-- 'skipped' stays parked until it is put back in the queue. The owner-facing "link
-- this family" action calls this so the backlog flows the moment the number lands.
create or replace function public.ghl_retry_skipped(p_profile_id uuid)
returns integer language plpgsql security definer set search_path = public as $$
declare n integer;
begin
  -- security definer bypasses RLS, so the caller's right to touch this location is
  -- checked here explicitly rather than being assumed from the table policy.
  if public.my_role() <> 'admin' then
    raise exception 'only an admin can requeue GHL items';
  end if;

  update public.ghl_outbox o
     set status = 'pending', attempts = 0, last_error = null, updated_at = now()
   where o.profile_id = p_profile_id
     and o.status = 'skipped'
     and o.location_id = public.my_location();

  get diagnostics n = row_count;
  return n;
end $$;

revoke all on function public.ghl_retry_skipped(uuid) from public, anon;
grant execute on function public.ghl_retry_skipped(uuid) to authenticated;
