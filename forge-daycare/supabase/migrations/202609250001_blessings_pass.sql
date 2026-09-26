-- Blessings Pass (spec: docs/superpowers/specs/2026-09-25-blessings-pass-design.md).
--
-- Two progress tracks per child, both COMPUTED on read from attendance + behavior_events
-- (never stored, so nothing can drift and the app snapshot's row caps can't undercount):
--   * Season Pass — XP inside the active season's dates: +100 per day checked in, +50 more
--     if that day ended green (a day with no behavior moves reads green, as everywhere else).
--     level = least(max_level, xp / xp_per_level + 1). Resets every season.
--   * Lifetime Rank — days attended, plus pre-app tenure credited as the weekdays between
--     enrollment_date and the child's first attendance row. Never resets.
--
-- Rewards: 'coins' drop Blessing Coins into the existing coin_transactions ledger (its
-- triggers stamp location, notify the parent, clamp redemptions); 'prize' (free lunch, free
-- day, discount…) lands in pass_claims unfulfilled until a manager applies it by hand.
-- NOTHING here touches invoices, and no money amount is seeded — the owner types those in.
--
-- Config (seasons, rewards, ranks) is edited by management — the owner dashboard calls
-- PostgREST with the manager's own JWT, so it goes through the write policies below. Claims
-- are written only through the security-definer RPCs at the bottom.

-- ---------------------------------------------------------------------------
-- 1. enrollment_date now drives rank. "parents update linked child profile" let a parent
--    rewrite it; lock it with the other management-owned columns.
-- ---------------------------------------------------------------------------
create or replace function public.guard_child_update()
returns trigger
language plpgsql
security definer
set search_path to 'public'
as $$
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
  new.enrollment_date := old.enrollment_date;
  return new;
end $$;

-- ---------------------------------------------------------------------------
-- 2. Leaderboard nicknames. Server-picked from fixed kid-safe word lists — no free text,
--    so nothing to moderate. Own table (not a children column) so the child guard above
--    never has to know about it. No policies: read only through the pass RPCs.
-- ---------------------------------------------------------------------------
create table public.child_nicknames (
  child_id uuid primary key references public.children(id) on delete cascade,
  location_id uuid not null references public.locations(id) on delete cascade,
  nickname text not null,
  unique (location_id, nickname)
);
alter table public.child_nicknames enable row level security;
revoke all on public.child_nicknames from anon, authenticated;

create or replace function public.assign_child_nickname(p_child uuid)
returns text
language plpgsql
security definer
set search_path to 'public'
as $$
declare
  adj text[] := array['Brave','Bright','Bubbly','Cheerful','Clever','Cozy','Daring','Dazzling',
    'Gentle','Giggly','Happy','Jolly','Kind','Lucky','Mighty','Merry','Nimble','Peppy','Plucky',
    'Quick','Shiny','Silly','Sparkly','Speedy','Sunny','Swift','Twinkly','Zippy','Bouncy','Starry'];
  ani text[] := array['Panda','Tiger','Otter','Koala','Penguin','Dolphin','Bunny','Fox','Owl',
    'Lion','Puppy','Kitten','Turtle','Giraffe','Zebra','Monkey','Elephant','Bear','Hedgehog',
    'Lamb','Duckling','Parrot','Seal','Unicorn','Dragon','Pony','Squirrel','Beaver','Whale','Flamingo'];
  v_loc uuid;
  v_nick text;
  i int := 0;
begin
  select location_id into v_loc from public.children where id = p_child;
  if v_loc is null then
    raise exception 'unknown child %', p_child using errcode = 'foreign_key_violation';
  end if;
  loop
    i := i + 1;
    -- 900 combos per centre; after 20 collisions fall back to a numbered suffix.
    v_nick := adj[1 + floor(random() * array_length(adj, 1))::int] || ' '
           || ani[1 + floor(random() * array_length(ani, 1))::int]
           || case when i > 20 then ' ' || i else '' end;
    begin
      insert into public.child_nicknames (child_id, location_id, nickname)
      values (p_child, v_loc, v_nick)
      on conflict (child_id) do update set nickname = excluded.nickname, location_id = excluded.location_id;
      return v_nick;
    exception when unique_violation then
      if i > 60 then raise; end if;
    end;
  end loop;
end $$;

create or replace function public.child_nickname_on_insert()
returns trigger
language plpgsql
security definer
set search_path to 'public'
as $$
begin
  perform public.assign_child_nickname(new.id);
  return new;
end $$;

create trigger child_nickname_assign after insert on public.children
for each row execute function public.child_nickname_on_insert();

select public.assign_child_nickname(c.id)
from public.children c
where not exists (select 1 from public.child_nicknames n where n.child_id = c.id);

-- ---------------------------------------------------------------------------
-- 3. Ranks, seasons, rewards, claims.
-- ---------------------------------------------------------------------------
create table public.pass_ranks (
  id uuid primary key default gen_random_uuid(),
  location_id uuid not null references public.locations(id) on delete cascade,
  min_days integer not null check (min_days >= 0),
  name text not null,
  perk text,                                   -- owner-typed; null = no perk
  unique (location_id, min_days)
);

create table public.pass_seasons (
  id uuid primary key default gen_random_uuid(),
  location_id uuid not null references public.locations(id) on delete cascade,
  name text not null,
  starts_on date not null,
  ends_on date not null,
  xp_per_level integer not null default 400 check (xp_per_level > 0),
  max_level integer not null default 20 check (max_level between 1 and 100),
  created_at timestamptz not null default now(),
  check (ends_on >= starts_on)
);
create index pass_seasons_location on public.pass_seasons (location_id, starts_on desc);

create table public.pass_rewards (
  id uuid primary key default gen_random_uuid(),
  season_id uuid not null references public.pass_seasons(id) on delete cascade,
  level integer not null check (level >= 1),
  title text not null,
  description text,
  kind text not null check (kind in ('coins', 'prize')),
  coin_amount integer,
  constraint pass_reward_amount check (
    (kind = 'coins' and coin_amount > 0) or (kind = 'prize' and coin_amount is null)
  ),
  unique (season_id, level, title)
);

-- A claim is history: no update/delete from clients. Coin claims are fulfilled on the spot;
-- prize claims wait for fulfill_pass_claim(). The FK to pass_rewards has no cascade, so a
-- season with claims can't be deleted out from under a family.
create table public.pass_claims (
  id uuid primary key default gen_random_uuid(),
  child_id uuid not null references public.children(id) on delete cascade,
  reward_id uuid not null references public.pass_rewards(id),
  claimed_by uuid references public.profiles(id) on delete set null,
  claimed_at timestamptz not null default now(),
  fulfilled_by uuid references public.profiles(id) on delete set null,
  fulfilled_at timestamptz,
  unique (child_id, reward_id)
);
create index pass_claims_open on public.pass_claims (claimed_at) where fulfilled_at is null;

alter table public.pass_ranks enable row level security;
alter table public.pass_seasons enable row level security;
alter table public.pass_rewards enable row level security;
alter table public.pass_claims enable row level security;
revoke all on public.pass_ranks, public.pass_seasons, public.pass_rewards, public.pass_claims from anon;

create policy "location reads ranks" on public.pass_ranks
  for select using (location_id = public.my_location());
create policy "location reads seasons" on public.pass_seasons
  for select using (location_id = public.my_location());
create policy "location reads rewards" on public.pass_rewards
  for select using (exists (
    select 1 from public.pass_seasons s where s.id = season_id and s.location_id = public.my_location()
  ));
create policy "scoped claim read" on public.pass_claims
  for select using (public.can_access_child(child_id));
-- Management edits its own centre's config. pass_claims gets no write policy at all:
-- claim_pass_reward() / fulfill_pass_claim() are the only way in.
create policy "management writes ranks" on public.pass_ranks
  for all using (public.my_role() in ('manager', 'admin') and location_id = public.my_location())
  with check (public.my_role() in ('manager', 'admin') and location_id = public.my_location());
create policy "management writes seasons" on public.pass_seasons
  for all using (public.my_role() in ('manager', 'admin') and location_id = public.my_location())
  with check (public.my_role() in ('manager', 'admin') and location_id = public.my_location());
create policy "management writes rewards" on public.pass_rewards
  for all using (public.my_role() in ('manager', 'admin') and exists (
    select 1 from public.pass_seasons s where s.id = season_id and s.location_id = public.my_location()))
  with check (public.my_role() in ('manager', 'admin') and exists (
    select 1 from public.pass_seasons s where s.id = season_id and s.location_id = public.my_location()));

-- Default ladder for every centre. Names are editable in the dashboard; perks start empty.
insert into public.pass_ranks (location_id, min_days, name)
select l.id, x.min_days, x.name
from public.locations l
cross join (values
  (0, 'Recruit'), (20, 'Cadet'), (50, 'Corporal'), (100, 'Sergeant'), (175, 'Lieutenant'),
  (250, 'Captain'), (350, 'Major'), (500, 'Colonel'), (700, 'General'), (1000, 'Legend')
) as x(min_days, name);

-- QA sandbox only: a live season with coin rewards and one clearly-labelled test prize.
-- Real centres get their seasons from the owner in the dashboard.
insert into public.pass_seasons (id, location_id, name, starts_on, ends_on)
values ('99999999-0000-0000-0000-000000000001', '99999999-9999-9999-9999-999999999999',
        'QA Season', date '2026-09-01', date '2026-12-31')
on conflict do nothing;
insert into public.pass_rewards (season_id, level, title, kind, coin_amount)
select '99999999-0000-0000-0000-000000000001', x.level, x.title, x.kind, x.amount
from (values
  (1, '10 Blessing Coins', 'coins', 10),
  (2, '15 Blessing Coins', 'coins', 15),
  (3, 'TEST prize — not real', 'prize', null),
  (5, '25 Blessing Coins', 'coins', 25)
) as x(level, title, kind, amount)
where exists (select 1 from public.locations where id = '99999999-9999-9999-9999-999999999999');

-- ---------------------------------------------------------------------------
-- 4. Computation (internal — not callable by clients).
-- ---------------------------------------------------------------------------
create or replace function public.pass_active_season(p_location uuid)
returns public.pass_seasons
language sql
stable
security definer
set search_path to 'public'
as $$
  select s.*
  from public.pass_seasons s
  join public.locations l on l.id = s.location_id
  where s.location_id = p_location
    and (now() at time zone l.timezone)::date between s.starts_on and s.ends_on
  order by s.starts_on desc
  limit 1
$$;

-- ponytail: scans the child's full attendance + behavior history per call; fine at a few
-- hundred children, materialize per-day XP if the leaderboard ever gets slow.
create or replace function public.pass_child_stats(p_child uuid, p_season uuid)
returns table (season_xp integer, lifetime_days integer)
language sql
stable
security definer
set search_path to 'public'
as $$
  with c as (
    select ch.enrollment_date, (now() at time zone l.timezone)::date as today
    from public.children ch
    join public.locations l on l.id = ch.location_id
    where ch.id = p_child
  ),
  s as (select starts_on, ends_on from public.pass_seasons where id = p_season),
  att as (select a.attendance_date from public.attendance a where a.child_id = p_child),
  day_color as (
    select distinct on (b.behavior_date) b.behavior_date, b.color
    from public.behavior_events b
    where b.child_id = p_child
    order by b.behavior_date, b.created_at desc
  )
  select
    coalesce((
      select sum(100 + case when coalesce(dc.color, 'green') = 'green' then 50 else 0 end)
      from att
      join s on att.attendance_date between s.starts_on and s.ends_on
      left join day_color dc on dc.behavior_date = att.attendance_date
    ), 0)::int,
    ((select count(*) from att)
     + (select count(*)
        from c, generate_series(c.enrollment_date,
                                coalesce((select min(attendance_date) from att), c.today) - 1,
                                interval '1 day') g
        where extract(isodow from g) < 6))::int
$$;

revoke all on function public.assign_child_nickname(uuid) from public, anon, authenticated;
revoke all on function public.child_nickname_on_insert() from public, anon, authenticated;
revoke all on function public.pass_active_season(uuid) from public, anon, authenticated;
revoke all on function public.pass_child_stats(uuid, uuid) from public, anon, authenticated;

-- ---------------------------------------------------------------------------
-- 5. Client RPCs.
-- ---------------------------------------------------------------------------

-- Everything the Pass screen needs for one child, in one call.
create or replace function public.pass_progress(p_child uuid)
returns jsonb
language plpgsql
stable
security definer
set search_path to 'public'
as $$
declare
  v_loc uuid;
  v_season public.pass_seasons;
  v_xp int;
  v_days int;
  v_rank public.pass_ranks;
  v_next public.pass_ranks;
begin
  if auth.uid() is not null and not public.can_access_child(p_child) then
    raise exception 'not allowed' using errcode = '42501';
  end if;
  select location_id into v_loc from public.children where id = p_child;
  v_season := public.pass_active_season(v_loc);
  select st.season_xp, st.lifetime_days into v_xp, v_days from public.pass_child_stats(p_child, v_season.id) st;
  select * into v_rank from public.pass_ranks
    where location_id = v_loc and min_days <= v_days order by min_days desc limit 1;
  select * into v_next from public.pass_ranks
    where location_id = v_loc and min_days > v_days order by min_days limit 1;

  return jsonb_build_object(
    'child_id', p_child,
    'nickname', (select nickname from public.child_nicknames where child_id = p_child),
    'lifetime_days', v_days,
    'rank', case when v_rank.id is null then null else
      jsonb_build_object('name', v_rank.name, 'min_days', v_rank.min_days, 'perk', v_rank.perk) end,
    'next_rank', case when v_next.id is null then null else
      jsonb_build_object('name', v_next.name, 'min_days', v_next.min_days) end,
    'season', case when v_season.id is null then null else
      jsonb_build_object('id', v_season.id, 'name', v_season.name, 'starts_on', v_season.starts_on,
        'ends_on', v_season.ends_on, 'xp_per_level', v_season.xp_per_level, 'max_level', v_season.max_level) end,
    'xp', v_xp,
    'level', case when v_season.id is null then 0
      else least(v_season.max_level, v_xp / v_season.xp_per_level + 1) end,
    'rewards', coalesce((
      select jsonb_agg(jsonb_build_object(
        'id', r.id, 'level', r.level, 'title', r.title, 'description', r.description,
        'kind', r.kind, 'coin_amount', r.coin_amount,
        'claimed_at', pc.claimed_at, 'fulfilled_at', pc.fulfilled_at
      ) order by r.level, r.title)
      from public.pass_rewards r
      left join public.pass_claims pc on pc.reward_id = r.id and pc.child_id = p_child
      where r.season_id = v_season.id
    ), '[]'::jsonb)
  );
end $$;

-- Centre leaderboard for the active season. Everyone at the location sees nickname,
-- classroom, level, XP and rank; the real name (first + last initial) and child_id come back
-- only for children the caller can already access (a parent's own kids, a teacher's class,
-- the whole centre for management). A caller with no JWT (service role / SQL editor)
-- passes p_location and sees all.
create or replace function public.pass_leaderboard(p_location uuid default null)
returns table (
  place integer, child_id uuid, child_name text, nickname text, classroom text,
  level integer, xp integer, lifetime_days integer, rank_name text, is_mine boolean
)
language plpgsql
stable
security definer
set search_path to 'public'
as $$
#variable_conflict use_column
declare
  v_service boolean := auth.uid() is null;
  v_loc uuid;
  v_season public.pass_seasons;
begin
  v_loc := case when v_service then p_location else public.my_location() end;
  if v_loc is null then return; end if;
  v_season := public.pass_active_season(v_loc);

  return query
  with r as (
    select ch.id, ch.first_name, ch.last_name, cl.name as classroom, st.season_xp, st.lifetime_days,
           (v_service or public.can_access_child(ch.id)) as visible,
           (not v_service and public.can_access_child(ch.id)) as mine
    from public.children ch
    left join public.classrooms cl on cl.id = ch.classroom_id
    cross join lateral public.pass_child_stats(ch.id, v_season.id) st
    where ch.location_id = v_loc and ch.active
  )
  select
    (row_number() over (order by r.season_xp desc, r.lifetime_days desc, n.nickname))::int,
    case when r.visible then r.id end,
    case when r.visible then r.first_name || ' ' || left(r.last_name, 1) || '.' end,
    n.nickname,
    r.classroom,
    case when v_season.id is null then 0
      else least(v_season.max_level, r.season_xp / v_season.xp_per_level + 1) end,
    r.season_xp,
    r.lifetime_days,
    (select pr.name from public.pass_ranks pr
      where pr.location_id = v_loc and pr.min_days <= r.lifetime_days
      order by pr.min_days desc limit 1),
    r.mine
  from r
  left join public.child_nicknames n on n.child_id = r.id
  order by 1;
end $$;

-- Parent (or staff) claims an unlocked reward for a child they can access.
create or replace function public.claim_pass_reward(p_child uuid, p_reward uuid)
returns public.pass_claims
language plpgsql
security definer
set search_path to 'public'
as $$
declare
  v_loc uuid;
  v_reward public.pass_rewards;
  v_season public.pass_seasons;
  v_xp int;
  v_claim public.pass_claims;
begin
  if auth.uid() is null or not public.can_access_child(p_child) then
    raise exception 'not allowed' using errcode = '42501';
  end if;
  select location_id into v_loc from public.children where id = p_child;
  select * into v_reward from public.pass_rewards where id = p_reward;
  v_season := public.pass_active_season(v_loc);
  if v_reward.id is null or v_season.id is null or v_reward.season_id <> v_season.id then
    raise exception 'That reward isn''t in this season''s pass.' using errcode = 'P0001';
  end if;
  select st.season_xp into v_xp from public.pass_child_stats(p_child, v_season.id) st;
  if least(v_season.max_level, v_xp / v_season.xp_per_level + 1) < v_reward.level then
    raise exception 'Reach level % to claim this reward.', v_reward.level using errcode = 'P0001';
  end if;

  insert into public.pass_claims (child_id, reward_id, claimed_by, fulfilled_at, fulfilled_by)
  values (p_child, p_reward, auth.uid(),
          case when v_reward.kind = 'coins' then now() end,
          case when v_reward.kind = 'coins' then auth.uid() end)
  on conflict (child_id, reward_id) do nothing
  returning * into v_claim;
  if v_claim.id is null then
    raise exception 'Already claimed.' using errcode = 'P0001';
  end if;

  if v_reward.kind = 'coins' then
    insert into public.coin_transactions (child_id, location_id, kind, amount, reason_label, actor_id)
    values (p_child, v_loc, 'award', v_reward.coin_amount, 'Season Pass · Level ' || v_reward.level, auth.uid());
  end if;
  return v_claim;
end $$;

create or replace function public.reroll_child_nickname(p_child uuid)
returns text
language plpgsql
security definer
set search_path to 'public'
as $$
begin
  if auth.uid() is null or not public.can_access_child(p_child) then
    raise exception 'not allowed' using errcode = '42501';
  end if;
  return public.assign_child_nickname(p_child);
end $$;

-- Manager marks a prize handed over (free lunch served, discount credited on the invoice…).
create or replace function public.fulfill_pass_claim(p_claim uuid)
returns public.pass_claims
language plpgsql
security definer
set search_path to 'public'
as $$
declare
  v_claim public.pass_claims;
begin
  select * into v_claim from public.pass_claims where id = p_claim;
  if v_claim.id is null
     or public.my_role() not in ('manager', 'admin')
     or not public.can_access_child(v_claim.child_id) then
    raise exception 'not allowed' using errcode = '42501';
  end if;
  update public.pass_claims
     set fulfilled_at = now(), fulfilled_by = auth.uid()
   where id = p_claim and fulfilled_at is null
  returning * into v_claim;
  return v_claim;
end $$;

revoke all on function public.pass_progress(uuid) from public, anon;
revoke all on function public.pass_leaderboard(uuid) from public, anon;
revoke all on function public.claim_pass_reward(uuid, uuid) from public, anon;
revoke all on function public.reroll_child_nickname(uuid) from public, anon;
revoke all on function public.fulfill_pass_claim(uuid) from public, anon;
grant execute on function public.pass_progress(uuid) to authenticated, service_role;
grant execute on function public.pass_leaderboard(uuid) to authenticated, service_role;
grant execute on function public.claim_pass_reward(uuid, uuid) to authenticated;
grant execute on function public.reroll_child_nickname(uuid) to authenticated;
grant execute on function public.fulfill_pass_claim(uuid) to authenticated;
