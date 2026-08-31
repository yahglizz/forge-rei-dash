-- F-1B-2: management closing a shift whose break is still running left
-- break_started_at dangling and never banked the break into break_seconds, so the
-- whole break was silently paid. The staff clock-out path already banks a running
-- break (202608070001); the management branch returned before any break handling.
--
-- Fix: in the management branch, whenever the row ends up closed with a break still
-- marked running, bank the break up to the clock-out moment (never negative — a
-- clock-out set before the break started banks zero) and clear break_started_at.
-- This runs BEFORE the edited_by/edited_at stamp check so a banking-only change
-- still stamps the row and lands in the shift_edits audit log. It also self-heals
-- any already-broken closed-with-dangling-break row on its next management edit.
-- Staff branch is unchanged from 202608070001.

create or replace function public.guard_staff_shift_update() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if public.my_role() is distinct from 'staff' then
    -- A closed row must not carry a running break. Bank it against the clock-out
    -- time, exactly as the staff clock-out path does, clamped at zero.
    if new.clocked_out_at is not null and new.break_started_at is not null then
      new.break_seconds := new.break_seconds
        + greatest(0, extract(epoch from (new.clocked_out_at - new.break_started_at))::integer);
      new.break_started_at := null;
    end if;
    -- Management correcting a punch. Stamp who and when so the row itself carries it.
    if new.clocked_in_at is distinct from old.clocked_in_at
      or new.clocked_out_at is distinct from old.clocked_out_at
      or new.break_seconds is distinct from old.break_seconds then
      new.edited_by := auth.uid();
      new.edited_at := clock_timestamp();
    end if;
    return new;
  end if;

  -- Staff may close their own shift and punch breaks. Nothing else.
  new.staff_id := old.staff_id;
  new.clocked_in_at := old.clocked_in_at;
  new.edited_by := old.edited_by;
  new.edited_at := old.edited_at;
  new.edit_reason := old.edit_reason;

  if old.break_started_at is null and new.break_started_at is not null then
    new.break_started_at := clock_timestamp();           -- break start
    new.break_seconds := old.break_seconds;
  elsif old.break_started_at is not null and new.break_started_at is null then
    new.break_seconds := old.break_seconds                -- break end
      + greatest(0, extract(epoch from (clock_timestamp() - old.break_started_at))::integer);
  else
    new.break_started_at := old.break_started_at;
    new.break_seconds := old.break_seconds;
  end if;

  if old.clocked_out_at is not null then
    new.clocked_out_at := old.clocked_out_at;             -- a closed shift stays closed
  elsif new.clocked_out_at is not null then
    new.clocked_out_at := clock_timestamp();
    -- Clocking out mid-break ends the break rather than leaving it running forever.
    if new.break_started_at is not null then
      new.break_seconds := new.break_seconds
        + greatest(0, extract(epoch from (clock_timestamp() - new.break_started_at))::integer);
      new.break_started_at := null;
    end if;
  end if;
  return new;
end $$;

-- The trigger from 202608070001 already binds this function; recreate defensively
-- so replaying this file alone on a schema that has the table still wires it up.
drop trigger if exists staff_shift_update_guard on public.staff_shifts;
create trigger staff_shift_update_guard before update on public.staff_shifts
  for each row execute function public.guard_staff_shift_update();
