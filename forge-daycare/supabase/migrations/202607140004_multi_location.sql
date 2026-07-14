-- 202607140004_multi_location.sql
-- Multi-location: one dashboard, many centers, still strictly separated.
--
-- WHY THIS SHAPE. Every RLS policy in this schema (~60 of them) scopes rows with
-- `location_id = my_location()`, and can_access_child() does too. So rather than
-- rewrite 60 policies -- the risky path, whose failure mode is a SILENT cross-center
-- data leak -- we change the single function they all call. my_location() becomes
-- membership-aware: it returns the caller's ACTIVE location when they are a member
-- of it, and otherwise falls back to their home location exactly as before.
--
-- Consequences, by construction:
--   * Parents and staff are provably unaffected. They have no profile_locations rows
--     and a NULL active_location_id, so my_location() returns profiles.location_id --
--     bit-for-bit the value it returned before this migration.
--   * A member "stands inside" exactly ONE center at a time. Centers stay walled off;
--     the owner just chooses which side of the wall to stand on. No policy is loosened.
--   * Escape is impossible: if active_location_id names a location the caller is NOT a
--     member of, the membership test fails and we fall back to home. A user writing that
--     column directly (via PostgREST) therefore gains nothing -- the guard is the
--     membership check here, never the column value.
--
-- Additive only, per CLAUDE.md rule 5. No policy is dropped or altered. The one new
-- policy is PERMISSIVE, and Postgres OR's permissive policies -- so it can only ever
-- ADD access, and only to profiles that have an explicit membership row.
--
-- NOTE: this file must stay byte-identical with the parent app's copy in
-- `the main daycare app/supabase/migrations/` (single source of truth).

-- ---------------------------------------------------------------------------
-- 1. Membership: which centers a profile may stand in. Empty for everyone by
--    default, which is why this migration is a no-op until we enroll someone.
-- ---------------------------------------------------------------------------
create table if not exists public.profile_locations (
  profile_id  uuid not null references public.profiles(id)  on delete cascade,
  location_id uuid not null references public.locations(id) on delete cascade,
  created_at  timestamptz not null default now(),
  primary key (profile_id, location_id)
);

alter table public.profile_locations enable row level security;

drop policy if exists "members read own location memberships" on public.profile_locations;
create policy "members read own location memberships"
  on public.profile_locations
  for select
  using (profile_id = auth.uid());

-- ---------------------------------------------------------------------------
-- 2. Which center the caller is currently standing in. NULL = home location,
--    which is the state every existing profile is in after this migration.
-- ---------------------------------------------------------------------------
alter table public.profiles
  add column if not exists active_location_id uuid references public.locations(id);

-- ---------------------------------------------------------------------------
-- 3. The lever. Same signature, same return type -- all ~60 policies and
--    can_access_child() pick this up with no edit.
-- ---------------------------------------------------------------------------
create or replace function public.my_location()
returns uuid
language sql
stable
security definer
set search_path to 'public'
as $function$
  select case
    when p.active_location_id is not null
     and exists (
       select 1 from public.profile_locations pl
       where pl.profile_id  = p.id
         and pl.location_id = p.active_location_id
     )
    then p.active_location_id
    else p.location_id
  end
  from public.profiles p
  where p.id = auth.uid()
$function$;

-- ---------------------------------------------------------------------------
-- 4. Let a member SEE the centers they belong to, so the switcher can list them.
--    Without this the existing policy (id = my_location()) shows exactly one row
--    and the dropdown would have nothing to draw. PERMISSIVE => OR'd => additive.
-- ---------------------------------------------------------------------------
drop policy if exists "members read their locations" on public.locations;
create policy "members read their locations"
  on public.locations
  for select
  using (
    exists (
      select 1 from public.profile_locations pl
      where pl.profile_id  = auth.uid()
        and pl.location_id = public.locations.id
    )
  );

-- ---------------------------------------------------------------------------
-- 5. The ONLY sanctioned way to move between centers. SECURITY DEFINER so it can
--    write the column, but it refuses any location the caller isn't a member of.
--    Passing NULL returns the caller to their home location.
-- ---------------------------------------------------------------------------
create or replace function public.set_active_location(target uuid)
returns uuid
language plpgsql
volatile
security definer
set search_path to 'public'
as $function$
declare
  home uuid;
begin
  if auth.uid() is null then
    raise exception 'not authenticated';
  end if;

  if target is null then
    update public.profiles set active_location_id = null where id = auth.uid();
    select location_id into home from public.profiles where id = auth.uid();
    return home;
  end if;

  if not exists (
    select 1 from public.profile_locations pl
    where pl.profile_id = auth.uid() and pl.location_id = target
  ) then
    raise exception 'not a member of that location';
  end if;

  update public.profiles set active_location_id = target where id = auth.uid();
  return target;
end
$function$;

revoke all on function public.set_active_location(uuid) from public;
grant execute on function public.set_active_location(uuid) to authenticated;
