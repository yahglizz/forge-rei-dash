-- Sign-in / sign-out sheets for CCS reporting.
--
-- Three things live here:
--   1. Tap-to-sign signatures on attendance (the ESIGN-style attestation).
--   2. One canonical definition of "hours" as a view, so the PDF and the app can
--      never disagree about what a child's day added up to.
--   3. The archive table + private bucket the generated PDFs land in.
--
-- The cron schedule is deliberately NOT here — it needs the deployed function URL
-- and a vault secret, so it lands in 202608080002 after the function exists.

-- ---------------------------------------------------------------------------
-- 1. Signatures
-- ---------------------------------------------------------------------------

-- A typed signature ("tap to sign", DocuSign-style). The text is what the person
-- typed; the timestamp and signer are stamped by the trigger below from the server
-- clock and the live JWT, never from the client. A signature whose time or author
-- the client can choose is not evidence of anything.
alter table public.attendance
  add column if not exists signature_in text,
  add column if not exists signature_in_at timestamptz,
  add column if not exists signature_in_by uuid references public.profiles(id),
  add column if not exists signature_out text,
  add column if not exists signature_out_at timestamptz,
  add column if not exists signature_out_by uuid references public.profiles(id);

do $$ begin
  alter table public.attendance add constraint attendance_signature_in_shape
    check (signature_in is null or char_length(btrim(signature_in)) between 2 and 120);
exception when duplicate_object then null; end $$;

do $$ begin
  alter table public.attendance add constraint attendance_signature_out_shape
    check (signature_out is null or char_length(btrim(signature_out)) between 2 and 120);
exception when duplicate_object then null; end $$;

-- Append-only, for EVERY role including the owner. Management can correct a wrong
-- punch time (that is a clerical fix, and staff_shifts already audits its own); a
-- signature is somebody's attestation that they personally handed the child over.
-- Rewriting one is forgery, so the database simply will not do it — there is no
-- privileged path, no reason column, no override.
create or replace function public.guard_attendance_signature() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if tg_op = 'INSERT' then
    if new.signature_in is not null then
      new.signature_in    := btrim(new.signature_in);
      new.signature_in_at := clock_timestamp();
      new.signature_in_by := auth.uid();
    else
      new.signature_in_at := null;
      new.signature_in_by := null;
    end if;
    -- A record cannot be born already signed out.
    new.signature_out    := null;
    new.signature_out_at := null;
    new.signature_out_by := null;
    return new;
  end if;

  -- UPDATE. Each signature moves null -> signed exactly once and then freezes.
  if old.signature_in is not null then
    new.signature_in    := old.signature_in;
    new.signature_in_at := old.signature_in_at;
    new.signature_in_by := old.signature_in_by;
  elsif new.signature_in is not null then
    new.signature_in    := btrim(new.signature_in);
    new.signature_in_at := clock_timestamp();
    new.signature_in_by := auth.uid();
  else
    new.signature_in_at := null;
    new.signature_in_by := null;
  end if;

  if old.signature_out is not null then
    new.signature_out    := old.signature_out;
    new.signature_out_at := old.signature_out_at;
    new.signature_out_by := old.signature_out_by;
  elsif new.signature_out is not null then
    new.signature_out    := btrim(new.signature_out);
    new.signature_out_at := clock_timestamp();
    new.signature_out_by := auth.uid();
  else
    new.signature_out_at := null;
    new.signature_out_by := null;
  end if;

  return new;
end $$;

-- The `zz_` prefix is load-bearing, not a typo. Postgres fires BEFORE triggers in
-- alphabetical order, and `attendance_update_guard` (the parent custody clamp)
-- rewrites columns on the same row. Sorting this one last means nothing runs after
-- it that could undo the freeze.
drop trigger if exists attendance_zz_signature_guard on public.attendance;
create trigger attendance_zz_signature_guard
  before insert or update on public.attendance
  for each row execute function public.guard_attendance_signature();

-- ---------------------------------------------------------------------------
-- 2. Hours — one definition, used by the PDF and the app alike
-- ---------------------------------------------------------------------------

-- security_invoker keeps the caller's RLS on `attendance` and `children`: the view
-- is a convenience, not a way around row security. A child still in the building
-- has null hours rather than 0 — an open day is unknown, not empty, and rendering
-- it as 0.00 on a subsidy claim would understate the hours.
create or replace view public.attendance_hours
with (security_invoker = on) as
select
  a.id,
  a.child_id,
  c.location_id,
  c.classroom_id,
  a.attendance_date,
  a.checked_in_at,
  a.checked_out_at,
  a.signature_in,
  a.signature_out,
  case
    when a.checked_out_at is null then null
    else round(extract(epoch from (a.checked_out_at - a.checked_in_at)) / 3600.0, 2)
  end as hours
from public.attendance a
join public.children c on c.id = a.child_id;

-- Supabase's default privileges hand anon/authenticated full DML on every new public
-- object. A join view is not auto-updatable so those writes would error today — but
-- "it happens to fail" is not an access control. This is a reporting view; SELECT is
-- the only verb it should own.
revoke all on public.attendance_hours from anon, authenticated;
grant select on public.attendance_hours to authenticated, service_role;

-- ---------------------------------------------------------------------------
-- 3. Archive
-- ---------------------------------------------------------------------------

create table if not exists public.signin_sheets (
  id uuid primary key default gen_random_uuid(),
  location_id uuid not null references public.locations(id) on delete cascade,
  classroom_id uuid references public.classrooms(id) on delete set null,  -- null = whole center
  period_kind text not null check (period_kind in ('daily', 'weekly')),
  period_start date not null,
  period_end date not null,
  storage_path text not null unique,
  child_count integer not null default 0,
  hours_total numeric(8,2) not null default 0,
  generated_at timestamptz not null default now(),
  generated_by uuid references public.profiles(id),   -- null = the scheduled run
  check (period_end >= period_start)
);

-- `nulls not distinct` so the all-center row (classroom_id is null) collides with
-- itself on a re-run. Without it, pressing Generate twice would silently stack up
-- duplicate all-center sheets for the same day.
do $$ begin
  alter table public.signin_sheets add constraint signin_sheets_one_per_period
    unique nulls not distinct (location_id, classroom_id, period_kind, period_start);
exception when duplicate_object then null; end $$;

create index if not exists signin_sheets_browse_idx
  on public.signin_sheets (location_id, period_start desc, period_kind);

alter table public.signin_sheets enable row level security;

-- Read-only to clients. Rows are written by the generator (service role) so that a
-- "sheet exists" claim always corresponds to a file that was really produced.
drop policy if exists "management reads signin sheets" on public.signin_sheets;
create policy "management reads signin sheets" on public.signin_sheets for select
using (public.my_role() in ('manager', 'admin') and location_id = public.my_location());

-- ---------------------------------------------------------------------------
-- 4. Bucket
-- ---------------------------------------------------------------------------

-- Private. These name every child in the building and when they leave it.
insert into storage.buckets (id, name, public)
values ('signin-sheets', 'signin-sheets', false)
on conflict (id) do nothing;

-- Path scheme is {location_id}/{kind}/{yyyy}/{mm}/{file}.pdf, so the first path
-- segment is the tenant key the policy checks.
drop policy if exists "management reads signin sheet files" on storage.objects;
create policy "management reads signin sheet files" on storage.objects for select
using (
  bucket_id = 'signin-sheets'
  and public.my_role() in ('manager', 'admin')
  and (storage.foldername(name))[1] = public.my_location()::text
);
