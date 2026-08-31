-- Atomic claim for the outbox drain.
--
-- ghl-push runs on a one-minute cron. If a drain ever takes longer than a minute the
-- next tick starts while the first is still mid-flight, and both would post the same
-- message into the family's GHL conversation. Claiming the rows first — a single
-- UPDATE ... FOR UPDATE SKIP LOCKED — makes that impossible without a lock table.

alter table public.ghl_outbox drop constraint if exists ghl_outbox_status_check;
alter table public.ghl_outbox add constraint ghl_outbox_status_check
  check (status in ('pending','sending','sent','skipped','failed'));

create or replace function public.ghl_claim_outbox(p_limit int default 25)
returns setof public.ghl_outbox
language plpgsql security definer set search_path = public as $$
begin
  -- Park anything that has burned through its retries. A row that keeps failing is a
  -- broken mapping, and retrying it forever buries the rows behind it.
  update public.ghl_outbox
     set status = 'failed', updated_at = now()
   where status = 'pending' and attempts >= 5;

  return query
  update public.ghl_outbox o
     set status = 'sending', attempts = o.attempts + 1, updated_at = now()
   where o.id in (
     select id from public.ghl_outbox
      where (status = 'pending' and attempts < 5)
         -- A run killed mid-flight (function timeout, deploy) leaves rows stuck in
         -- 'sending' forever. Anything older than five minutes is fair game again.
         or (status = 'sending' and updated_at < now() - interval '5 minutes')
      order by created_at
      limit p_limit
      for update skip locked
   )
  returning o.*;
end $$;

revoke all on function public.ghl_claim_outbox(int) from public, anon, authenticated;
grant execute on function public.ghl_claim_outbox(int) to service_role;
