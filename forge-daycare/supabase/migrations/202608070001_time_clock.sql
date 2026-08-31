-- Time clock: break punches, tamper guards, an edit audit trail, and a pay-period
-- setting so management decides the cadence instead of the code hard-coding one.
--
-- Before this, `staff_shifts` was the least protected table in the schema. The
-- SELECT/INSERT/UPDATE policies scoped rows to `my_staff_id()` and stopped there, so
-- a staff member could `update staff_shifts set clocked_in_at = '04:00'` on their own
-- row, re-open a closed shift by nulling `clocked_out_at`, or insert one backdated to
-- last Tuesday. Payroll is computed from these rows, so that is a self-service raise.
-- `children` and `attendance` already got this treatment (20260713183905, 202608060002);
-- this is the same pattern applied to the table that decides what people are paid.

-- ---------------------------------------------------------------------------
-- 1. Columns
-- ---------------------------------------------------------------------------

-- break_started_at marks a break in progress; break_seconds is the accumulated
-- unpaid total, always computed by the trigger below and never taken from the
-- client — a shorter break means a bigger paycheck, so it is not the punching
-- party's number to supply.
alter table public.staff_shifts
  add column if not exists break_started_at timestamptz,
  add column if not exists break_seconds integer not null default 0,
  add column if not exists edited_by uuid references public.profiles(id),
  add column if not exists edited_at timestamptz,
  add column if not exists edit_reason text;

do $$ begin
  alter table public.staff_shifts add constraint staff_shifts_break_seconds_nonneg check (break_seconds >= 0);
exception when duplicate_object then null; end $$;

-- `>=`, not `>`: now() is the transaction timestamp, so a clock-in and a clock-out
-- landing in one transaction are equal, not increasing. A zero-length shift is
-- meaningless but harmless; a punch that hard-errors instead of saving is not.
do $$ begin
  alter table public.staff_shifts add constraint staff_shifts_out_after_in
    check (clocked_out_at is null or clocked_out_at >= clocked_in_at);
exception when duplicate_object then null; end $$;

-- One open shift per person. The clock button branched purely on client state, so two
-- devices (or one stale tab) could each insert an open row and the hours would double.
create unique index if not exists staff_shifts_one_open_per_staff
  on public.staff_shifts (staff_id) where clocked_out_at is null;

-- Pay period is management's call, not the code's. Anchor is the first day of any
-- period; every other period is derived from it, so a Sun–Sat week and a Mon–Sun week
-- are the same feature with a different anchor. Overtime stays weekly (FLSA 29 USC 207
-- has no daily threshold, and neither does Pennsylvania).
alter table public.locations
  add column if not exists pay_period text not null default 'biweekly',
  add column if not exists pay_period_anchor date not null default date '2026-01-05',
  add column if not exists overtime_weekly_hours numeric(5,2) not null default 40;

do $$ begin
  alter table public.locations add constraint locations_pay_period_valid
    check (pay_period in ('weekly', 'biweekly', 'semimonthly'));
exception when duplicate_object then null; end $$;

-- ---------------------------------------------------------------------------
-- 2. Audit trail
-- ---------------------------------------------------------------------------

-- A corrected punch keeps the original. Overwriting is what makes "we fixed a typo"
-- indistinguishable from "we shaved an hour" if the state ever audits, or if a staff
-- member disputes a check. FLSA recordkeeping (29 CFR 516) wants the record to reflect
-- hours actually worked; this is how we can still show what it said before.
create table if not exists public.shift_edits (
  id uuid primary key default gen_random_uuid(),
  shift_id uuid not null references public.staff_shifts(id) on delete cascade,
  staff_id uuid not null references public.staff_members(id) on delete cascade,
  edited_by uuid references public.profiles(id),
  edited_at timestamptz not null default now(),
  reason text,
  before jsonb not null,
  after jsonb not null
);

create index if not exists shift_edits_shift_idx on public.shift_edits (shift_id, edited_at desc);

alter table public.shift_edits enable row level security;

-- Read only: rows are written by the trigger (security definer), never by a client.
drop policy if exists "staff read own or management shift edits" on public.shift_edits;
create policy "staff read own or management shift edits" on public.shift_edits for select
using (
  staff_id = public.my_staff_id()
  or (public.my_role() in ('manager', 'admin') and exists (
    select 1 from public.staff_members s where s.id = staff_id and s.location_id = public.my_location()))
);

-- ---------------------------------------------------------------------------
-- 3. Guards
-- ---------------------------------------------------------------------------

-- `is distinct from`, not `<>`: my_role() is NULL with no end-user JWT (service role,
-- edge function, SQL console) and `NULL <> 'staff'` is NULL, not true — which silently
-- turned the children/attendance guards into no-ops in 202608060004.
create or replace function public.guard_staff_shift_insert() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if public.my_role() is distinct from 'staff' then return new; end if;
  -- A staff punch is always the moment of the statement. clock_timestamp(), not now():
  -- now() is frozen at transaction start, so a clock-in and clock-out in one
  -- transaction come out equal and a break measures as zero seconds.
  new.clocked_in_at := clock_timestamp();
  new.clocked_out_at := null;
  new.break_started_at := null;
  new.break_seconds := 0;
  new.edited_by := null;
  new.edited_at := null;
  new.edit_reason := null;
  return new;
end $$;

create or replace function public.guard_staff_shift_update() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if public.my_role() is distinct from 'staff' then
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

create or replace function public.log_staff_shift_edit() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if new.clocked_in_at is not distinct from old.clocked_in_at
    and new.clocked_out_at is not distinct from old.clocked_out_at
    and new.break_seconds is not distinct from old.break_seconds then
    return null;                                          -- nothing payable changed
  end if;
  if public.my_role() is not distinct from 'staff' then
    return null;                                          -- own punch, own clock, not an edit
  end if;
  insert into public.shift_edits (shift_id, staff_id, edited_by, reason, before, after)
  values (
    new.id, new.staff_id, auth.uid(), new.edit_reason,
    jsonb_build_object('clocked_in_at', old.clocked_in_at, 'clocked_out_at', old.clocked_out_at, 'break_seconds', old.break_seconds),
    jsonb_build_object('clocked_in_at', new.clocked_in_at, 'clocked_out_at', new.clocked_out_at, 'break_seconds', new.break_seconds)
  );
  return null;
end $$;

drop trigger if exists staff_shift_insert_guard on public.staff_shifts;
create trigger staff_shift_insert_guard before insert on public.staff_shifts
  for each row execute function public.guard_staff_shift_insert();

drop trigger if exists staff_shift_update_guard on public.staff_shifts;
create trigger staff_shift_update_guard before update on public.staff_shifts
  for each row execute function public.guard_staff_shift_update();

drop trigger if exists staff_shift_edit_log on public.staff_shifts;
create trigger staff_shift_edit_log after update on public.staff_shifts
  for each row execute function public.log_staff_shift_edit();

-- ---------------------------------------------------------------------------
-- 4. Management can insert a shift on someone's behalf (missed punch)
-- ---------------------------------------------------------------------------
-- The existing insert policy already allows manager/admin at the location; the guard
-- above leaves their supplied timestamps alone. Deleting a punch stays impossible for
-- everyone — there is no DELETE policy on staff_shifts, and that is deliberate: a
-- wrong punch gets corrected, with the original preserved, never erased.
