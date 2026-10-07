-- 202610070001_pass_stay_xp_curve_give_xp.sql
-- Spec: docs/superpowers/specs/2026-10-06-pass-xp-stay-curve-give-xp.md (owner ask 2026-10-06).
--
-- 1. Daily XP keeps the +100 for signing in and the +50 green day, and adds stay XP:
--    +5 for every full 30 minutes between sign-in and sign-out, up to 10 hours (+100).
--    A visit with no sign-out yet counts to the parent's pickup request, else to "now" but no
--    further than the center's full_day_hours — so XP never drops overnight, and signing out
--    properly is what earns a long day.
-- 2. Levels get harder as they go: level L -> L+1 costs xp_per_level + xp_growth * (L - 1).
--    One helper (pass_level) now decides the level everywhere, including the claim check.
-- 3. Staff "Give XP": a bonus-XP ledger written only through give_pass_xp(). 1-50 a tap,
--    at most 50 a child per center day, needs an active season. Management corrections are
--    signed negative adjustments that can only take back bonus XP.
-- Re-runnable.

-- ---------------------------------------------------------------------------
-- 1. Level curve
-- ---------------------------------------------------------------------------
alter table public.pass_seasons add column if not exists xp_growth integer not null default 50;
do $$ begin
  alter table public.pass_seasons add constraint pass_seasons_xp_growth_range check (xp_growth between 0 and 1000);
exception when duplicate_object then null; end $$;

-- Season 1 (Harvest of Blessings at ATOB + ATOB 2) and the QA sandbox move to the curve.
-- No family at a real center had claimed anything when this shipped.
update public.pass_seasons set xp_per_level = 200, xp_growth = 50
 where id in ('43803ee6-f129-4c0c-bee2-3e4f09307f51', '5d8d87b0-1949-43ba-aed9-12a7c21d695e',
              '99999999-0000-0000-0000-000000000001')
   and xp_per_level = 400;

-- XP a child needs to stand at the start of p_level (level 1 = 0).
create or replace function public.pass_level_xp(p_level integer, p_per integer, p_growth integer)
returns integer language sql immutable set search_path to 'public' as $$
  select ((greatest(p_level, 1) - 1) * p_per + p_growth * (greatest(p_level, 1) - 1) * (greatest(p_level, 1) - 2) / 2)::int
$$;

-- Level for an XP total: 1 + every level whose floor the child has reached. growth 0 = the
-- old flat xp / xp_per_level + 1. (pass_seasons checks xp_per_level > 0, xp_growth >= 0.)
create or replace function public.pass_level(p_xp integer, p_per integer, p_growth integer, p_max integer)
returns integer language sql immutable set search_path to 'public' as $$
  select (1 + count(*))::int from generate_series(2, greatest(p_max, 1)) l
   where public.pass_level_xp(l, p_per, p_growth) <= greatest(coalesce(p_xp, 0), 0)
$$;

-- ---------------------------------------------------------------------------
-- 2. Bonus XP ledger
-- ---------------------------------------------------------------------------
create table if not exists public.pass_xp_awards (
  id uuid primary key default gen_random_uuid(),
  child_id uuid not null references public.children(id) on delete cascade,
  location_id uuid not null references public.locations(id),
  season_id uuid not null references public.pass_seasons(id),
  award_date date not null,
  kind text not null check (kind in ('award', 'adjustment')),
  amount integer not null,
  reason_label text not null check (char_length(btrim(reason_label)) between 1 and 60),
  note text check (note is null or char_length(note) <= 200),
  actor_id uuid not null references public.profiles(id),
  created_at timestamptz not null default now(),
  constraint pass_xp_award_shape check (
    (kind = 'award' and amount between 1 and 50)
    or (kind = 'adjustment' and amount < 0 and note is not null)
  )
);
create index if not exists pass_xp_awards_child on public.pass_xp_awards (child_id, season_id);
alter table public.pass_xp_awards enable row level security;
drop policy if exists "scoped xp read" on public.pass_xp_awards;
create policy "scoped xp read" on public.pass_xp_awards for select using (public.can_access_child(child_id));
-- No insert/update/delete policies: written only by give_pass_xp(), never edited.

do $$ begin
  alter publication supabase_realtime add table public.pass_xp_awards;
exception when duplicate_object then null; end $$;

-- ---------------------------------------------------------------------------
-- 3. Computation
-- ---------------------------------------------------------------------------
create or replace function public.pass_child_stats(p_child uuid, p_season uuid)
returns table (season_xp integer, lifetime_days integer)
language sql
stable
security definer
set search_path to 'public'
as $$
  with c as (
    select ch.enrollment_date, (now() at time zone l.timezone)::date as today, l.full_day_hours
    from public.children ch
    join public.locations l on l.id = ch.location_id
    where ch.id = p_child
  ),
  s as (select starts_on, ends_on from public.pass_seasons where id = p_season),
  att as (
    select a.attendance_date, a.checked_in_at,
           coalesce(a.checked_out_at, a.pickup_requested_at,
                    least(now(), a.checked_in_at + c.full_day_hours * interval '1 hour')) as ended_at
    from public.attendance a, c
    where a.child_id = p_child
  ),
  day_color as (
    select distinct on (b.behavior_date) b.behavior_date, b.color
    from public.behavior_events b
    where b.child_id = p_child
    order by b.behavior_date, b.created_at desc
  )
  select
    (coalesce((
      select sum(100
                 + 5 * greatest(0, floor(extract(epoch from
                     least(att.ended_at, att.checked_in_at + interval '10 hours') - att.checked_in_at) / 1800))::int
                 + case when coalesce(dc.color, 'green') = 'green' then 50 else 0 end)
      from att
      join s on att.attendance_date between s.starts_on and s.ends_on
      left join day_color dc on dc.behavior_date = att.attendance_date
    ), 0)
    + coalesce((select sum(x.amount) from public.pass_xp_awards x
                where x.child_id = p_child and x.season_id = p_season), 0))::int,
    ((select count(*) from att)
     + (select count(*)
        from c, generate_series(c.enrollment_date,
                                coalesce((select min(attendance_date) from att), c.today) - 1,
                                interval '1 day') g
        where extract(isodow from g) < 6))::int
$$;

revoke all on function public.pass_level_xp(integer, integer, integer) from public, anon, authenticated;
revoke all on function public.pass_level(integer, integer, integer, integer) from public, anon, authenticated;
revoke all on function public.pass_child_stats(uuid, uuid) from public, anon, authenticated;

-- ---------------------------------------------------------------------------
-- 4. Every reader of the level goes through pass_level(). Bodies are the live definitions
--    (pg_get_functiondef, 2026-10-06) with only the level lines changed; signatures and
--    return types are identical, so existing grants stay. pass_progress adds xp_growth,
--    level_floor_xp and next_level_xp; app_tracking's JSON shape is unchanged.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.pass_progress(p_child uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
declare
  v_loc uuid;
  v_season public.pass_seasons;
  v_xp int;
  v_days int;
  v_rank public.pass_ranks;
  v_next public.pass_ranks;
  v_level int;
begin
  if auth.uid() is not null and not public.can_access_child(p_child) then
    raise exception 'not allowed' using errcode = '42501';
  end if;
  select location_id into v_loc from public.children where id = p_child;
  v_season := public.pass_active_season(v_loc);
  select st.season_xp, st.lifetime_days into v_xp, v_days from public.pass_child_stats(p_child, v_season.id) st;
  v_level := case when v_season.id is null then 0
    else public.pass_level(v_xp, v_season.xp_per_level, v_season.xp_growth, v_season.max_level) end;
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
        'ends_on', v_season.ends_on, 'xp_per_level', v_season.xp_per_level, 'xp_growth', v_season.xp_growth,
        'max_level', v_season.max_level) end,
    'xp', v_xp,
    'level', v_level,
    'level_floor_xp', case when v_season.id is null then 0
      else public.pass_level_xp(v_level, v_season.xp_per_level, v_season.xp_growth) end,
    'next_level_xp', case when v_season.id is null or v_level >= v_season.max_level then null
      else public.pass_level_xp(v_level + 1, v_season.xp_per_level, v_season.xp_growth) end,
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
end $function$;

CREATE OR REPLACE FUNCTION public.pass_leaderboard(p_location uuid DEFAULT NULL::uuid)
 RETURNS TABLE(place integer, child_id uuid, child_name text, nickname text, classroom text, level integer, xp integer, lifetime_days integer, rank_name text, is_mine boolean)
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
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
      else public.pass_level(r.season_xp, v_season.xp_per_level, v_season.xp_growth, v_season.max_level) end,
    r.season_xp,
    r.lifetime_days,
    (select pr.name from public.pass_ranks pr
      where pr.location_id = v_loc and pr.min_days <= r.lifetime_days
      order by pr.min_days desc limit 1),
    r.mine
  from r
  left join public.child_nicknames n on n.child_id = r.id
  order by 1;
end $function$;

CREATE OR REPLACE FUNCTION public.claim_pass_reward(p_child uuid, p_reward uuid)
 RETURNS pass_claims
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
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
  if public.pass_level(v_xp, v_season.xp_per_level, v_season.xp_growth, v_season.max_level) < v_reward.level then
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
end $function$;

CREATE OR REPLACE FUNCTION public.notify_pass_progress(p_child uuid)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
declare
  v_child  public.children%rowtype;
  v_season public.pass_seasons;
  v_xp     int;
  v_days   int;
  v_level  int;
  v_rank   public.pass_ranks;
  v_seen   public.pass_level_seen%rowtype;
  v_name   text;
  v_unlock text;
begin
  select * into v_child from public.children where id = p_child;
  if not found then return; end if;
  v_season := public.pass_active_season(v_child.location_id);
  if v_season.id is null then return; end if;
  select st.season_xp, st.lifetime_days into v_xp, v_days from public.pass_child_stats(p_child, v_season.id) st;
  -- Same formula as pass_progress().
  v_level := public.pass_level(v_xp, v_season.xp_per_level, v_season.xp_growth, v_season.max_level);
  select * into v_rank from public.pass_ranks
   where location_id = v_child.location_id and min_days <= v_days order by min_days desc limit 1;

  select * into v_seen from public.pass_level_seen where child_id = p_child for update;
  if not found or v_seen.season_id is distinct from v_season.id then
    insert into public.pass_level_seen (child_id, season_id, level, rank_min)
    values (p_child, v_season.id, v_level, coalesce(v_rank.min_days, 0))
    on conflict (child_id) do update set season_id = excluded.season_id, level = excluded.level,
      rank_min = excluded.rank_min, updated_at = now();
    return;
  end if;

  v_name := coalesce(nullif(btrim(v_child.preferred_name), ''), v_child.first_name);

  if v_level > v_seen.level then
    select string_agg(r.title, ', ' order by r.level, r.title) into v_unlock
      from public.pass_rewards r
     where r.season_id = v_season.id and r.level > v_seen.level and r.level <= v_level;
    insert into public.notifications (profile_id, kind, title, body, link)
    select gp.profile_id, 'pass', v_name || ' reached Level ' || v_level || '!',
      case when v_unlock is not null
        then 'New reward unlocked: ' || v_unlock || '. Claim it on the Blessings Pass.'
        when v_level >= v_season.max_level then v_name || ' hit the top level of ' || v_season.name || '!'
        else 'Every day at the center earns XP. Level ' || (v_level + 1) || ' is next.' end,
      null
    from public.ghl_child_parents(p_child) gp;
  end if;

  if v_rank.id is not null and v_rank.min_days > v_seen.rank_min then
    insert into public.notifications (profile_id, kind, title, body, link)
    select gp.profile_id, 'pass', v_name || ' is now a ' || v_rank.name || '!',
      'A new rank after ' || v_days || ' days with us.' || coalesce(' Perk: ' || nullif(btrim(v_rank.perk), '') || '.', ''),
      null
    from public.ghl_child_parents(p_child) gp;
  end if;

  update public.pass_level_seen
     set level = greatest(v_seen.level, v_level),
         rank_min = greatest(v_seen.rank_min, coalesce(v_rank.min_days, 0)),
         updated_at = now()
   where child_id = p_child;
end $function$;

CREATE OR REPLACE FUNCTION public.app_tracking(p_location uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
declare
  v_caller public.profiles;
  v_season public.pass_seasons;
  v_families jsonb;
  v_children jsonb;
begin
  select * into v_caller from public.profiles where id = auth.uid();
  if v_caller.id is null or not v_caller.active or v_caller.role <> 'admin'
     or not (v_caller.location_id = p_location
             or exists (select 1 from public.profile_locations pl
                        where pl.profile_id = v_caller.id and pl.location_id = p_location)) then
    raise exception 'Only an admin of this center can read app tracking' using errcode = '42501';
  end if;

  v_season := public.pass_active_season(p_location);

  select coalesce(jsonb_agg(f.j order by (f.j->>'last_sign_in_at') is not null, f.j->>'name'), '[]'::jsonb)
    into v_families
  from (
    select jsonb_build_object(
      'profile_id', p.id,
      'name', coalesce(nullif(p.display_name, ''), trim(concat_ws(' ', p.first_name, p.last_name))),
      'login_id', p.login_id,
      'has_login', p.login_id is not null,
      'last_sign_in_at', u.last_sign_in_at,
      'push_devices', (select count(*) from public.push_subscriptions s
                       where s.profile_id = p.id and s.disabled_at is null),
      'autopay_on', coalesce((select a.enabled from public.family_autopay a where a.profile_id = p.id), false),
      'unpaid_invoices', (select count(*) from public.invoices i
                          where i.guardian_id = g.id and i.status in ('due', 'overdue')),
      'unpaid_total', (select coalesce(sum(i.amount), 0) from public.invoices i
                       where i.guardian_id = g.id and i.status in ('due', 'overdue')),
      'last_payment_at', lp.paid_at,
      'last_payment_amount', lp.amount
    ) as j
    from public.profiles p
    left join auth.users u on u.id = p.id
    left join public.guardians g on g.profile_id = p.id
    left join lateral (
      select pm.paid_at, pm.amount from public.payments pm
      join public.invoices i on i.id = pm.invoice_id
      where i.guardian_id = g.id order by pm.paid_at desc limit 1
    ) lp on true
    where p.role = 'parent' and p.active and p.location_id = p_location
  ) f;

  select coalesce(jsonb_agg(k.j order by k.j->>'name'), '[]'::jsonb) into v_children
  from (
    select jsonb_build_object(
      'child_id', c.id,
      'name', trim(concat_ws(' ', c.first_name, c.last_name)),
      'nickname', (select n.nickname from public.child_nicknames n where n.child_id = c.id),
      'classroom', cr.name,
      'guardian_profile_id', c.guardian_profile_id,
      'coin_balance', (select coalesce(sum(t.amount), 0) from public.coin_transactions t where t.child_id = c.id),
      'recent_coins', coalesce((select jsonb_agg(x order by x.created_at desc) from (
          select t.kind, t.amount, t.reason_label, t.created_at from public.coin_transactions t
          where t.child_id = c.id order by t.created_at desc limit 10) x), '[]'::jsonb),
      'open_orders', coalesce((select jsonb_agg(jsonb_build_object('order_no', o.order_no, 'total', o.total,
          'placed_at', o.placed_at) order by o.placed_at)
          from public.coin_orders o where o.child_id = c.id and o.status = 'pending'), '[]'::jsonb),
      'pass_xp', coalesce(st.season_xp, 0),
      'pass_level', case when v_season.id is null then 0
                         else public.pass_level(coalesce(st.season_xp, 0), v_season.xp_per_level, v_season.xp_growth, v_season.max_level) end,
      'rank_name', (select r.name from public.pass_ranks r
                    where r.location_id = p_location and r.min_days <= coalesce(st.lifetime_days, 0)
                    order by r.min_days desc limit 1),
      'prizes_owed', coalesce((select jsonb_agg(jsonb_build_object('title', pr.title, 'level', pr.level,
          'claimed_at', pc.claimed_at) order by pc.claimed_at)
          from public.pass_claims pc join public.pass_rewards pr on pr.id = pc.reward_id
          where pc.child_id = c.id and pc.fulfilled_at is null), '[]'::jsonb)
    ) as j
    from public.children c
    left join public.classrooms cr on cr.id = c.classroom_id
    left join lateral public.pass_child_stats(c.id, v_season.id) st on true
    where c.location_id = p_location and c.active
  ) k;

  return jsonb_build_object(
    'center', p_location,
    'generated_at', now(),
    'season', case when v_season.id is null then null else jsonb_build_object(
      'id', v_season.id, 'name', v_season.name, 'starts_on', v_season.starts_on, 'ends_on', v_season.ends_on) end,
    'families', v_families,
    'children', v_children,
    'leaderboard', coalesce((select jsonb_agg(jsonb_build_object('name', e->>'name', 'nickname', e->>'nickname',
        'pass_level', (e->>'pass_level')::int, 'pass_xp', (e->>'pass_xp')::int)
        order by (e->>'pass_xp')::int desc, e->>'name')
      from (select e from jsonb_array_elements(v_children) as x(e)
            where (e->>'pass_xp')::int > 0
            order by (e->>'pass_xp')::int desc, e->>'name' limit 5) top), '[]'::jsonb),
    'totals', jsonb_build_object(
      'families', jsonb_array_length(v_families),
      'signed_in_ever', (select count(*) from jsonb_array_elements(v_families) as x(e) where e->>'last_sign_in_at' is not null),
      'active_7d', (select count(*) from jsonb_array_elements(v_families) as x(e)
                    where (e->>'last_sign_in_at')::timestamptz > now() - interval '7 days'),
      'never_signed_in', (select count(*) from jsonb_array_elements(v_families) as x(e)
                          where (e->>'has_login')::boolean and e->>'last_sign_in_at' is null),
      'push_on', (select count(*) from jsonb_array_elements(v_families) as x(e) where (e->>'push_devices')::int > 0),
      'coins_outstanding', (select coalesce(sum((e->>'coin_balance')::numeric), 0) from jsonb_array_elements(v_children) as x(e)),
      'open_orders', (select coalesce(sum(jsonb_array_length(e->'open_orders')), 0) from jsonb_array_elements(v_children) as x(e)),
      'prizes_owed', (select coalesce(sum(jsonb_array_length(e->'prizes_owed')), 0) from jsonb_array_elements(v_children) as x(e)),
      'unpaid_total', (select coalesce(sum((e->>'unpaid_total')::numeric), 0) from jsonb_array_elements(v_families) as x(e)),
      'autopay_on', (select count(*) from jsonb_array_elements(v_families) as x(e) where (e->>'autopay_on')::boolean))
  );
end $function$;

-- ---------------------------------------------------------------------------
-- 5. Give XP
-- ---------------------------------------------------------------------------
-- One tap from the Rewards page. Each child is checked and locked on its own (sorted, so two
-- teachers tapping overlapping groups can't deadlock); a child who can't take it is skipped and
-- named back, never partially awarded. A negative amount is a manager's signed correction for
-- exactly one child and can only take back bonus XP.
create or replace function public.give_pass_xp(p_children uuid[], p_amount integer, p_reason text, p_note text default null)
returns jsonb
language plpgsql
security definer
set search_path to 'public'
as $$
declare
  v_role public.app_role := public.my_role();
  v_reason text := btrim(coalesce(p_reason, ''));
  v_note text := nullif(btrim(coalesce(p_note, '')), '');
  v_adjust boolean := coalesce(p_amount, 0) < 0;
  v_ids uuid[];
  v_id uuid;
  v_child public.children%rowtype;
  v_season public.pass_seasons;
  v_today date;
  v_sum int;
  v_name text;
  v_awarded uuid[] := '{}';
  v_skipped jsonb := '[]'::jsonb;
begin
  if auth.uid() is null or v_role is null or v_role not in ('staff', 'manager', 'admin') then
    raise exception 'not allowed' using errcode = '42501';
  end if;
  if p_amount is null or p_amount = 0 or p_amount > 50 then
    raise exception 'Give between 1 and 50 XP at a time.' using errcode = 'P0001';
  end if;
  if char_length(v_reason) not between 1 and 60 then
    raise exception 'Pick a reason for the XP.' using errcode = 'P0001';
  end if;
  if v_note is not null and char_length(v_note) > 200 then
    raise exception 'Keep the note under 200 characters.' using errcode = 'P0001';
  end if;
  select array_agg(distinct x order by x) into v_ids from unnest(p_children) x where x is not null;
  if v_ids is null then
    raise exception 'Pick at least one child first.' using errcode = 'P0001';
  end if;
  if cardinality(v_ids) > 60 then
    raise exception 'Give XP to 60 children or fewer at a time.' using errcode = 'P0001';
  end if;
  if v_adjust then
    if v_role not in ('manager', 'admin') then
      raise exception 'Only a manager can take XP back.' using errcode = '42501';
    end if;
    if cardinality(v_ids) <> 1 then
      raise exception 'Correct one child at a time.' using errcode = 'P0001';
    end if;
    if v_note is null then
      raise exception 'A correction needs a note.' using errcode = 'P0001';
    end if;
  end if;

  foreach v_id in array v_ids loop
    if not public.can_access_child(v_id) then
      if v_adjust then raise exception 'not allowed' using errcode = '42501'; end if;
      v_skipped := v_skipped || jsonb_build_object('child_id', v_id, 'reason', 'not_allowed');
      continue;
    end if;
    perform pg_advisory_xact_lock(hashtextextended('pass_xp:' || v_id::text, 0));
    select * into v_child from public.children where id = v_id;
    v_season := public.pass_active_season(v_child.location_id);
    if v_season.id is null then
      if v_adjust then raise exception 'No season is running at this center.' using errcode = 'P0001'; end if;
      v_skipped := v_skipped || jsonb_build_object('child_id', v_id, 'reason', 'no_season');
      continue;
    end if;
    select (now() at time zone l.timezone)::date into v_today from public.locations l where l.id = v_child.location_id;
    v_name := coalesce(nullif(btrim(v_child.preferred_name), ''), v_child.first_name);

    if v_adjust then
      select coalesce(sum(x.amount), 0) into v_sum from public.pass_xp_awards x
       where x.child_id = v_id and x.season_id = v_season.id;
      if v_sum + p_amount < 0 then
        raise exception '% only has % bonus XP this season to take back.', v_name, v_sum using errcode = 'P0001';
      end if;
    else
      select coalesce(sum(x.amount), 0) into v_sum from public.pass_xp_awards x
       where x.child_id = v_id and x.award_date = v_today and x.kind = 'award';
      if v_sum + p_amount > 50 then
        v_skipped := v_skipped || jsonb_build_object('child_id', v_id, 'reason', 'daily_cap', 'given_today', v_sum);
        continue;
      end if;
    end if;

    insert into public.pass_xp_awards (child_id, location_id, season_id, award_date, kind, amount, reason_label, note, actor_id)
    values (v_id, v_child.location_id, v_season.id, v_today,
            case when v_adjust then 'adjustment' else 'award' end, p_amount, v_reason, v_note, auth.uid());
    v_awarded := v_awarded || v_id;

    -- Alerts are best effort: they never undo the award.
    if not v_adjust then
      begin
        insert into public.notifications (profile_id, kind, title, body, link)
        select gp.profile_id, 'pass', v_name || ' earned +' || p_amount || ' XP!',
          v_name || ' got +' || p_amount || ' XP for ' || v_reason || ' on the Blessings Pass.', null
        from public.ghl_child_parents(v_id) gp;
      exception when others then
        raise warning 'give_pass_xp: % — XP kept, award alert skipped', sqlerrm;
      end;
    end if;
    begin
      perform public.notify_pass_progress(v_id);
    exception when others then
      raise warning 'give_pass_xp: % — XP kept, level alert skipped', sqlerrm;
    end;
  end loop;

  return jsonb_build_object('awarded', to_jsonb(v_awarded), 'skipped', v_skipped);
end $$;

revoke all on function public.give_pass_xp(uuid[], integer, text, text) from public, anon;
grant execute on function public.give_pass_xp(uuid[], integer, text, text) to authenticated;
revoke execute on function public.notify_pass_progress(uuid) from public, anon, authenticated;

-- ---------------------------------------------------------------------------
-- 6. Level alerts when a stay ends. A WHEN clause, not `update of`: the BEFORE guard writes
--    pickup_requested_at itself, and `update of` only sees the client's SET list.
-- ---------------------------------------------------------------------------
drop trigger if exists attendance_pass_progress_update on public.attendance;
create trigger attendance_pass_progress_update after update on public.attendance
for each row when (old.checked_out_at is distinct from new.checked_out_at
                   or old.pickup_requested_at is distinct from new.pickup_requested_at
                   or old.checked_in_at is distinct from new.checked_in_at)
execute function public.pass_progress_check();

-- ---------------------------------------------------------------------------
-- 7. The retune moves levels: record the new ones silently so no family gets a burst of
--    "reached Level N" alerts for a change in the rules.
-- ---------------------------------------------------------------------------
update public.pass_level_seen s
   set level = (select public.pass_level(st.season_xp, ps.xp_per_level, ps.xp_growth, ps.max_level)
                  from public.pass_child_stats(s.child_id, ps.id) st),
       updated_at = now()
  from public.pass_seasons ps
 where ps.id = s.season_id;
