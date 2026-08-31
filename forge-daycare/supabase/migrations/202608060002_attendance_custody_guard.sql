-- Chain of custody is a headline trust feature: the app shows parents "Picked up at
-- 5:12 PM · by Owner QA". But `scoped attendance update` is just can_access_child(),
-- and attendance had no guard trigger — so a parent could UPDATE their own child's
-- row and stamp any staff member's name on the pickup, or rewrite the morning
-- arrival. Proven against the live DB (rolled back): a parent set checked_out_by to
-- the owner's uuid and it wrote, 2 rows affected.
--
-- Mirrors the existing guard_child_update / guard_invoice_update pattern: the write
-- is allowed, the columns a parent must not author are clamped.
create or replace function public.guard_attendance_update() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if public.my_role() <> 'parent' then return new; end if;

  -- Arrival is the center's record. A parent may never rewrite it.
  new.child_id        := old.child_id;
  new.attendance_date := old.attendance_date;
  new.checked_in_at   := old.checked_in_at;
  new.checked_in_by   := old.checked_in_by;

  -- A parent may sign out, and may re-open the visit for a same-day re-entry
  -- (out for an appointment, back after lunch). Either way the pickup is
  -- attributed to them — they cannot put someone else's name on a custody record.
  if new.checked_out_at is null then
    new.checked_out_by := null;
  else
    new.checked_out_by := auth.uid();
  end if;

  return new;
end $$;

create trigger attendance_update_guard before update on public.attendance
for each row execute function public.guard_attendance_update();

revoke execute on function public.guard_attendance_update() from public, anon, authenticated;
