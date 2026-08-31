-- Move the QA cohort off the real center and into a sandbox location of its own.
--
-- WHY THIS EXISTS
-- The one-tap login block in .env.local is inlined into the shipped JS bundle by Next
-- (`NEXT_PUBLIC_*`), so the four QA Login IDs and PINs — including a MANAGER and an
-- ADMIN — are readable by anyone who opens the app's JavaScript. Those four accounts
-- lived at location 11111111-…-1111, "A Touch of Blessings", which is the owner's REAL
-- center: Dana Wells and her child Micah Wells are enrolled there and Nina Carter is
-- real staff. Anyone reading the bundle could therefore sign in and read — and write —
-- a real family's records.
--
-- 2026-08-06 closed a narrower version of this: BL-MGR-QA held profile_locations rows
-- for locations 2222 and 4444 and could set_active_location() into the other real
-- center. That fix deleted the foreign memberships but left the QA cohort sitting in
-- 1111 alongside real data. This finishes the job — the QA accounts now resolve to a
-- location that contains nothing but test rows, so a leaked test PIN buys a sandbox.
--
-- THE INVARIANT: no profile whose login_id matches 'BL-%-QA' may resolve to, or hold a
-- profile_locations row for, any location holding a non-QA child. It is asserted at the
-- bottom of this file, so a mistake anywhere above rolls the whole migration back.
--
-- WHAT MOVES: the 4 QA profiles, their staff/guardian rows, the 3 test children and
-- their classroom placement, and every location-scoped row belonging to them (coins,
-- the test invoice, the test message threads). Rows keyed only to a child or a staff
-- member — attendance, daily logs, incidents, behaviour events, shifts, payroll,
-- notifications — follow their parent row and are deliberately not touched.
--
-- WHAT DOES NOT MOVE: the 6 rows already in `signin_sheets` for location 1111. Those
-- are archived PDFs that really were generated against 1111 at the time, and rewriting
-- an archive to claim it came from somewhere else is worse than leaving it. They do
-- name the test children, so delete them by hand before that archive is ever handed to
-- a licensing inspector.

-- ---------------------------------------------------------------------------
-- 1. The sandbox location and its classroom
-- ---------------------------------------------------------------------------

insert into public.locations (id, name, address, timezone, opens_at, closes_at, pay_period, pay_period_anchor, overtime_weekly_hours)
select '99999999-9999-9999-9999-999999999999', 'QA Sandbox — test data only', 'Not a real center',
       src.timezone, src.opens_at, src.closes_at, src.pay_period, src.pay_period_anchor, src.overtime_weekly_hours
from public.locations src
where src.id = '11111111-1111-1111-1111-111111111111'
on conflict (id) do nothing;

insert into public.classrooms (id, location_id, name, age_group, capacity)
values ('99999999-0000-4000-8000-000000000001', '99999999-9999-9999-9999-999999999999', 'Little Lambs', 'Infant / Toddler', 8)
on conflict (id) do nothing;

-- ---------------------------------------------------------------------------
-- 2. The test children move FIRST
-- ---------------------------------------------------------------------------

-- Identified by guardianship, not by name: "Riley Parent" is a string a real family
-- could one day match, whereas being the QA parent's child cannot be. Doing this step
-- first means every statement below can say "the children at the sandbox" instead of
-- repeating this predicate — and it keeps the whole file free of hardcoded child ids.
update public.children
set location_id = '99999999-9999-9999-9999-999999999999',
    classroom_id = '99999999-0000-4000-8000-000000000001'
where guardian_profile_id in (select id from public.profiles where login_id like 'BL-%-QA')
   or exists (
     select 1 from public.guardian_children gc
     join public.guardians g on g.id = gc.guardian_id
     join public.profiles p on p.id = g.profile_id
     where gc.child_id = children.id and p.login_id like 'BL-%-QA'
   );

-- ---------------------------------------------------------------------------
-- 3. The people
-- ---------------------------------------------------------------------------

-- active_location_id is cleared rather than repointed: my_location() only honours it
-- when a matching profile_locations row exists, so a stale value is a silent fallback
-- waiting to happen. Home location is now the sandbox, which is the whole point.
update public.profiles
set location_id = '99999999-9999-9999-9999-999999999999', active_location_id = null
where login_id like 'BL-%-QA';

update public.profile_locations
set location_id = '99999999-9999-9999-9999-999999999999'
where profile_id in (select id from public.profiles where login_id like 'BL-%-QA');

update public.staff_members
set location_id = '99999999-9999-9999-9999-999999999999'
where profile_id in (select id from public.profiles where login_id like 'BL-%-QA');

update public.guardians
set location_id = '99999999-9999-9999-9999-999999999999'
where profile_id in (select id from public.profiles where login_id like 'BL-%-QA');

update public.staff_classrooms
set classroom_id = '99999999-0000-4000-8000-000000000001'
where staff_id in (
  select s.id from public.staff_members s
  where s.location_id = '99999999-9999-9999-9999-999999999999'
);

-- ---------------------------------------------------------------------------
-- 4. Reward catalog
-- ---------------------------------------------------------------------------

-- Copied, not moved: the real center keeps its own catalog. The existing QA redemptions
-- point at the 1111 rows, and a redemption row that joins a reward row inside the real
-- center is exactly the cross-location read this migration exists to remove — so they
-- are repointed at the copies, matched by name, in the same statement.
with src as (
  select id, name, description, cost, icon, active
  from public.reward_items
  where location_id = '11111111-1111-1111-1111-111111111111'
    and not exists (select 1 from public.reward_items where location_id = '99999999-9999-9999-9999-999999999999')
),
copied as (
  insert into public.reward_items (location_id, name, description, cost, icon, active)
  select '99999999-9999-9999-9999-999999999999', name, description, cost, icon, active from src
  returning id, name
)
update public.coin_transactions ct
set reward_item_id = copied.id
from copied join src on src.name = copied.name
where ct.reward_item_id = src.id;

-- ---------------------------------------------------------------------------
-- 5. Location-scoped rows belonging to the cohort
-- ---------------------------------------------------------------------------

update public.coin_transactions
set location_id = '99999999-9999-9999-9999-999999999999'
where child_id in (select id from public.children where location_id = '99999999-9999-9999-9999-999999999999');

-- Three guards freeze location_id and would turn these two updates into silent no-ops:
--   invoices.invoice_update_guard          — exempts my_role() in ('manager','admin'),
--                                            which is NULL here (a migration carries no
--                                            end-user JWT), so it freezes.
--   message_threads.message_thread_update_guard  — freezes unconditionally.
--   message_threads.thread_update_guard          — freezes unconditionally, and is easy
--                                            to miss: message_threads carries TWO
--                                            overlapping update guards. Disabling only
--                                            the first one left the threads behind at
--                                            the real center on the first run of this
--                                            file, with no error to say so.
--
-- The disable/enable pairs live inside a block with an exception handler rather than as
-- bare statements: if anything between them raises and this file is NOT running in one
-- transaction, bare statements would leave the invoice tamper guard switched OFF on a
-- live database — parents could then rewrite invoice amounts. The handler puts every
-- guard back before re-raising, so the failure mode is a failed migration rather than a
-- silently unprotected table.
do $$
begin
  alter table public.invoices disable trigger invoice_update_guard;
  alter table public.message_threads disable trigger message_thread_update_guard;
  alter table public.message_threads disable trigger thread_update_guard;

  -- `invoices.guardian_id` FKs to profiles, not guardians, despite the name — checked
  -- against the live constraint (invoices_guardian_id_fkey → profiles). Matching it
  -- against guardians.id would be a branch that can never fire.
  update public.invoices
  set location_id = '99999999-9999-9999-9999-999999999999'
  where child_id in (select id from public.children where location_id = '99999999-9999-9999-9999-999999999999')
     or guardian_id in (select id from public.profiles where login_id like 'BL-%-QA');

  -- A thread moves only when EVERY participant is QA. A mixed thread would drag a real
  -- person's messages into the sandbox, so those are left where they are — and the
  -- assertion below does not care about them, because a thread holds no children.
  update public.message_threads mt
  set location_id = '99999999-9999-9999-9999-999999999999'
  where exists (select 1 from public.thread_participants tp where tp.thread_id = mt.id)
    and not exists (
      select 1 from public.thread_participants tp
      join public.profiles p on p.id = tp.profile_id
      -- coalesce, not a bare NOT LIKE: a null login_id makes NOT LIKE evaluate to NULL,
      -- which would read as "no non-QA participant" and move a real person's thread.
      where tp.thread_id = mt.id and coalesce(p.login_id, '') not like 'BL-%-QA'
    );

  alter table public.invoices enable trigger invoice_update_guard;
  alter table public.message_threads enable trigger message_thread_update_guard;
  alter table public.message_threads enable trigger thread_update_guard;
exception when others then
  alter table public.invoices enable trigger invoice_update_guard;
  alter table public.message_threads enable trigger message_thread_update_guard;
  alter table public.message_threads enable trigger thread_update_guard;
  raise;
end $$;

-- ---------------------------------------------------------------------------
-- 6. Prove the invariant, or roll the whole thing back
-- ---------------------------------------------------------------------------

do $$
declare
  bad integer;
  detail text;
begin
  -- Every location a QA account can reach — home plus explicit memberships — checked
  -- for children that are not part of the QA cohort.
  select count(*), string_agg(distinct reach.login_id, ', ')
  into bad, detail
  from (
    select p.login_id, p.location_id as loc
    from public.profiles p where p.login_id like 'BL-%-QA'
    union
    select p.login_id, pl.location_id
    from public.profiles p join public.profile_locations pl on pl.profile_id = p.id
    where p.login_id like 'BL-%-QA'
  ) reach
  where exists (
    select 1 from public.children c
    where c.location_id = reach.loc
      and c.location_id is distinct from '99999999-9999-9999-9999-999999999999'
  );
  if bad > 0 then
    raise exception 'QA cohort still reaches a location holding children (% reachable location(s)): %', bad, detail;
  end if;

  -- The mirror check: only QA-guarded children may be standing in the sandbox.
  select count(*) into bad
  from public.children c
  where c.location_id = '99999999-9999-9999-9999-999999999999'
    and c.guardian_profile_id not in (select id from public.profiles where login_id like 'BL-%-QA')
    and not exists (
      select 1 from public.guardian_children gc
      join public.guardians g on g.id = gc.guardian_id
      join public.profiles gp on gp.id = g.profile_id
      where gc.child_id = c.id and gp.login_id like 'BL-%-QA'
    );
  if bad > 0 then
    raise exception '% non-QA child row(s) landed in the QA sandbox', bad;
  end if;

  -- And nothing of the cohort's may be left behind. The first run of this file moved
  -- the profiles, children, coins and invoice but silently left both all-QA message
  -- threads at the real center, because message_threads carries a second update guard
  -- that was not disabled. Asserting the outcome — rather than trusting the update to
  -- have matched — is what turns that class of miss into a failed migration.
  select count(*) into bad
  from public.message_threads mt
  where mt.location_id is distinct from '99999999-9999-9999-9999-999999999999'
    and exists (select 1 from public.thread_participants tp where tp.thread_id = mt.id)
    and not exists (
      select 1 from public.thread_participants tp
      join public.profiles p on p.id = tp.profile_id
      where tp.thread_id = mt.id and coalesce(p.login_id, '') not like 'BL-%-QA'
    );
  if bad > 0 then
    raise exception '% all-QA message thread(s) left outside the sandbox', bad;
  end if;
end $$;
