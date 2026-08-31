-- Backfill for 202608160001_shift_break_close_fix.sql.
--
-- That migration stopped management from closing a shift while a break was still
-- running without banking the break — but it only fixes shifts edited AFTER it was
-- applied. Rows already sitting in the broken shape (clocked_out_at set, and
-- break_started_at still not null) keep their break unbanked forever unless someone
-- happens to edit them again, and `shiftPaidHours()` in lib/timecard.ts only subtracts
-- a live break while the shift is OPEN — so a closed row like this pays the whole break.
-- A fix with no backfill leaves the money wrong on exactly the rows that proved the bug.
--
-- The banking rule is copied from the trigger, deliberately: same clamp at zero (a
-- clock-out recorded before the break started banks nothing rather than crediting
-- negative time), same source columns. One statement, both columns, no trigger needed.

update public.staff_shifts
set break_seconds = break_seconds
      + greatest(0, extract(epoch from (clocked_out_at - break_started_at))::integer),
    break_started_at = null,
    edit_reason = coalesce(edit_reason, 'backfill 202608170002: break banked at clock-out')
where clocked_out_at is not null
  and break_started_at is not null;

-- The shape must not exist afterwards. If it does, the update above did not match what
-- the trigger considers broken and the two definitions have drifted apart.
do $$
declare
  bad integer;
begin
  select count(*) into bad from public.staff_shifts
  where clocked_out_at is not null and break_started_at is not null;
  if bad > 0 then
    raise exception '% closed shift(s) still carry a running break', bad;
  end if;
end $$;
