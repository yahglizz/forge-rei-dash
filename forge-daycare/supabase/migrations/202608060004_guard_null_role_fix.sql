-- The tamper guards opened with `if public.my_role() <> 'parent' then return new; end if;`
-- my_role() is NULL whenever there is no end-user JWT — the service role, an edge
-- function, a SQL console. NULL <> 'parent' is NULL, not true, so the early return
-- never fired and execution fell through to the clamp, resetting every guarded column
-- to its old value. The write reported success and changed nothing: the same silent
-- postgrest failure this codebase keeps producing, this time inside Postgres.
--
-- `is distinct from` is the null-safe form. Parents are still clamped; everyone else
-- (including service-role callers) passes through. RLS remains the access gate.
create or replace function public.guard_child_update() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if public.my_role() is distinct from 'parent' then return new; end if;
  new.first_name := old.first_name;
  new.last_name := old.last_name;
  new.birth_date := old.birth_date;
  new.classroom_id := old.classroom_id;
  new.location_id := old.location_id;
  new.guardian_profile_id := old.guardian_profile_id;
  new.allergies := old.allergies;
  new.medical_notes := old.medical_notes;
  new.pickup_notes := old.pickup_notes;
  new.active := old.active;
  return new;
end $$;

create or replace function public.guard_attendance_update() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if public.my_role() is distinct from 'parent' then return new; end if;
  new.child_id        := old.child_id;
  new.attendance_date := old.attendance_date;
  new.checked_in_at   := old.checked_in_at;
  new.checked_in_by   := old.checked_in_by;
  if new.checked_out_at is null then new.checked_out_by := null;
  else new.checked_out_by := auth.uid(); end if;
  return new;
end $$;

-- Re-run 202608060003: it was applied while the guard above was still swallowing
-- service-role writes, so it reported success and updated nothing. Idempotent.
update public.children c
set guardian_profile_id = g.profile_id
from public.guardian_children gc
join public.guardians g on g.id = gc.guardian_id
join public.profiles p on p.id = g.profile_id
where gc.child_id = c.id
  and c.guardian_profile_id is null
  and p.location_id = c.location_id
  and p.active;
