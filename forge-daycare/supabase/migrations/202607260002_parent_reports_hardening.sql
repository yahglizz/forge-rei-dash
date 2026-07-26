-- Parent Concerns hardening (follow-up to 202607260001, which is already applied
-- live — never edit an applied migration). Three defects found in review:
--   1. the insert policy let a parent choose `status`, so a concern could arrive
--      pre-marked 'resolved' and skip the owner's triage entirely;
--   2. guard_parent_report_update clamped every column except the primary key,
--      so an admin UPDATE could move `id` even though only `status` may change;
--   3. a reply never touched its parent report, so the owner's inbox — which
--      sorts by updated_at — left a freshly answered concern buried.

-- 1. Triage state is the owner's alone; a report always starts at 'new'.
drop policy if exists "parents file reports" on public.parent_reports;
create policy "parents file reports" on public.parent_reports for insert
  with check (
    public.my_role() = 'parent'
    and author_id = auth.uid()
    and location_id = public.my_location()
    and status = 'new'
    and (child_id is null or public.can_access_child(child_id))
  );

-- 2. Pin the primary key too. Everything except `status` (and `updated_at`,
--    which parent_reports_touch re-stamps afterwards) is restored from old.
create or replace function public.guard_parent_report_update() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  new.id := old.id;
  new.location_id := old.location_id;
  new.author_id := old.author_id;
  new.child_id := old.child_id;
  new.subject := old.subject;
  new.body := old.body;
  new.attachment_path := old.attachment_path;
  new.created_at := old.created_at;
  return new;
end $$;
revoke execute on function public.guard_parent_report_update() from anon, authenticated, public;

-- 3. A reply is activity: bump the report so it sorts to the top of the inbox.
--    security definer because the replying parent has no UPDATE policy on
--    parent_reports (and must not get one) — this touches updated_at only, and
--    guard_parent_report_update still clamps the rest on the way through.
create or replace function public.touch_parent_report_on_reply() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  update public.parent_reports set updated_at = now() where id = new.report_id;
  return new;
end $$;
revoke execute on function public.touch_parent_report_on_reply() from anon, authenticated, public;

drop trigger if exists parent_report_reply_touch on public.parent_report_replies;
create trigger parent_report_reply_touch after insert on public.parent_report_replies
for each row execute function public.touch_parent_report_on_reply();
