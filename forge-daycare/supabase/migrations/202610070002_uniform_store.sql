-- 202610070002_uniform_store.sql
--
-- Owner-approved 2026-10-07 (Yahjair): a Uniform store. Families order a child's uniform shirt /
-- pants in the app and pay by card on a Stripe-hosted Checkout page (the webhook, never the
-- redirect, marks the order paid); staff hand the order over at the centre. The same catalog
-- carries an optional coin price: a child can redeem a free uniform with Blessing Coins, at most
-- 2 free items per child per school year (Aug 1 - Jul 31, US-Eastern, any mix of items).
--
-- Design: spec docs/superpowers/specs/2026-10-07-uniform-store-design.md (section 4).
-- Same shape as the coin store (202609270008): every write is ONE definer function that locks the
-- child, re-prices from the catalog (the client never sets a price), and is idempotent on a
-- request id. uniform_orders has NO write policies and no write grants.
-- Tuition / invoices / coin-store functions are not touched.

-- 1. School year: the year of the most recent Aug 1 boundary in America/New_York.
-- Aug 2026 .. Jul 2027 -> 2026. Evaluating the month in Eastern wall-clock time makes the
-- boundary DST-proof (Aug 1 00:00 EDT is 04:00Z).
create or replace function public.school_year_start(p_ts timestamptz)
returns integer
language sql
stable
set search_path to 'public'
as $$
  select (extract(year  from (p_ts at time zone 'America/New_York')))::int
       - case when extract(month from (p_ts at time zone 'America/New_York')) < 8 then 1 else 0 end
$$;

-- 2. Sizes jsonb: [{ "label": text, "in_stock": bool }] - 1..20 entries, non-empty labels of at
-- most 10 chars, unique case-insensitively, in_stock a real boolean.
create or replace function public.uniform_sizes_valid(p jsonb)
returns boolean
language plpgsql
immutable
set search_path to 'public'
as $$
declare
  e jsonb;
  l text;
  seen text[] := '{}';
begin
  if jsonb_typeof(p) is distinct from 'array' or jsonb_array_length(p) not between 1 and 20 then
    return false;
  end if;
  for e in select * from jsonb_array_elements(p) loop
    if jsonb_typeof(e) is distinct from 'object'
       or jsonb_typeof(e->'label') is distinct from 'string'
       or jsonb_typeof(e->'in_stock') is distinct from 'boolean' then
      return false;
    end if;
    l := lower(btrim(e->>'label'));
    if length(l) = 0 or length(e->>'label') > 10 or l = any(seen) then
      return false;
    end if;
    seen := seen || l;
  end loop;
  return true;
end $$;

-- 3. Catalog.
create table public.uniform_items (
  id uuid primary key default gen_random_uuid(),
  location_id uuid not null references public.locations(id),
  name text not null check (length(btrim(name)) between 1 and 60),
  kind text not null default 'other' check (kind in ('shirt', 'pants', 'other')),
  price_cents integer not null check (price_cents between 0 and 1000000),
  -- Non-null => redeemable free with coins. These items live ONLY here (never in reward_items).
  coin_cost integer check (coin_cost > 0),
  sizes jsonb not null check (public.uniform_sizes_valid(sizes)),
  image_path text,
  active boolean not null default true,
  sort integer not null default 0,
  created_at timestamptz not null default now()
);
create index uniform_items_location on public.uniform_items (location_id, sort, name);

-- 4. Orders.
create table public.uniform_orders (
  id uuid primary key default gen_random_uuid(),
  order_no bigint generated always as identity (start with 5001) unique,
  child_id uuid not null references public.children(id) on delete cascade,
  location_id uuid not null references public.locations(id),
  -- Receipt snapshot priced from the catalog at order time:
  -- [{uniform_item_id, name, size, qty, unit_cents, coin_cost}]. unit_cents is what was CHARGED per
  -- unit (0 on a coins order); coin_cost is null on a card order. A later catalog edit never
  -- rewrites a receipt.
  items jsonb not null check (jsonb_typeof(items) = 'array' and jsonb_array_length(items) between 1 and 20),
  pay_method text not null check (pay_method in ('card', 'coins')),
  total_cents integer not null check (total_cents >= 0),
  coins_paid integer not null default 0 check (coins_paid >= 0),
  status text not null default 'awaiting_payment'
    check (status in ('awaiting_payment', 'paid', 'handed_over', 'cancelled', 'expired')),
  stripe_session_id text unique,
  stripe_payment_intent text,
  request_id uuid not null unique,
  -- Counts against the per-child school-year cap. = total qty on a coins order, 0 on a card order.
  free_qty integer not null default 0 check (free_qty >= 0),
  school_year integer not null,
  debit_tx_id uuid references public.coin_transactions(id),
  refund_tx_id uuid references public.coin_transactions(id),
  placed_by uuid not null references public.profiles(id),
  placed_at timestamptz not null default now(),
  paid_at timestamptz,
  closed_by uuid references public.profiles(id),
  closed_at timestamptz,
  cancel_reason text,
  note text,
  constraint uniform_pay_shape check (
    (pay_method = 'coins' and total_cents = 0 and coins_paid > 0 and free_qty > 0)
    or (pay_method = 'card' and total_cents > 0 and coins_paid = 0 and free_qty = 0)),
  constraint uniform_closed_shape check ((status in ('handed_over', 'cancelled', 'expired')) = (closed_at is not null)),
  constraint uniform_paid_has_time check (status not in ('paid', 'handed_over') or paid_at is not null),
  constraint uniform_session_card_only check (stripe_session_id is null or pay_method = 'card')
);
create index uniform_orders_child_year on public.uniform_orders (child_id, school_year);
create index uniform_orders_child_placed on public.uniform_orders (child_id, placed_at desc);
create index uniform_orders_open on public.uniform_orders (location_id, placed_at)
  where status in ('awaiting_payment', 'paid');

-- 5. Row-level security.
alter table public.uniform_items enable row level security;
alter table public.uniform_orders enable row level security;

-- Families and staff see the active catalog of their centre; management sees every row.
create policy "active uniform catalog read" on public.uniform_items
  for select using (
    location_id = public.my_location()
    and (active or public.my_role() in ('manager', 'admin')));
-- Management writes within its own centre. No DELETE policy: retire an item with active=false.
create policy "management adds uniforms" on public.uniform_items
  for insert with check (public.my_role() in ('manager', 'admin') and location_id = public.my_location());
create policy "management edits uniforms" on public.uniform_items
  for update using (public.my_role() in ('manager', 'admin') and location_id = public.my_location())
  with check (public.my_role() in ('manager', 'admin') and location_id = public.my_location());
-- Orders read like the coin ledger: families their children, staff their classrooms, management the
-- centre. No write policy at all: every write goes through the functions below.
create policy "scoped uniform order read" on public.uniform_orders
  for select using (public.can_access_child(child_id));

-- Same restrictive gate the other tables carry (202610040001): a deactivated account reads nothing.
create policy "active account required" on public.uniform_items as restrictive for all to authenticated
  using ((select public.my_role()) is not null) with check ((select public.my_role()) is not null);
create policy "active account required" on public.uniform_orders as restrictive for all to authenticated
  using ((select public.my_role()) is not null) with check ((select public.my_role()) is not null);

-- Belt and braces: with no write grant a direct UPDATE/INSERT errors (42501) instead of silently
-- matching zero rows.
revoke all on public.uniform_items from anon, authenticated;
grant select, insert, update on public.uniform_items to authenticated;
revoke all on public.uniform_orders from anon, authenticated;
grant select on public.uniform_orders to authenticated;

do $$
begin
  alter publication supabase_realtime add table public.uniform_items;
exception when duplicate_object then null;
end $$;
do $$
begin
  alter publication supabase_realtime add table public.uniform_orders;
exception when duplicate_object then null;
end $$;

-- 6. Helpers (internal: callable only from the definer functions below).
create or replace function public.uniform_order_summary(p_items jsonb)
returns text
language sql
immutable
set search_path to 'public'
as $$
  select string_agg(case when (l->>'qty')::int > 1 then (l->>'qty') || '× ' else '' end
                    || (l->>'name') || ' (' || (l->>'size') || ')', ', ')
  from jsonb_array_elements(p_items) l;
$$;

create or replace function public.uniform_money(p_cents integer)
returns text
language sql
immutable
set search_path to 'public'
as $$ select '$' || to_char(p_cents / 100.0, 'FM999990.00') $$;

-- Validate + price a cart from the catalog. p_lines: [{uniform_item_id, size, qty}]. Extra keys
-- (a tampered price, say) are ignored. Duplicate item+size lines are merged. p_coins = redeeming
-- with coins: every item must carry a coin_cost.
create or replace function public.uniform_build_lines(
  p_location uuid, p_lines jsonb, p_coins boolean,
  out o_items jsonb, out o_total_cents integer, out o_total_coins integer, out o_qty integer)
language plpgsql
set search_path to 'public'
as $$
declare
  v_line jsonb;
  v_raw text;
  v_id uuid;
  v_size text;
  v_qty int;
  v_n int;
  i int;
  v_ids uuid[] := '{}';
  v_sizes text[] := '{}';
  v_qtys int[] := '{}';
  v_item public.uniform_items;
  sz jsonb;
  v_found boolean;
  v_stock boolean;
  v_unit int;
  v_coin int;
begin
  if jsonb_typeof(p_lines) is distinct from 'array' or jsonb_array_length(p_lines) not between 1 and 20 then
    raise exception 'The cart is empty.' using errcode = '22023';
  end if;

  for v_line in select * from jsonb_array_elements(p_lines) loop
    if jsonb_typeof(v_line) is distinct from 'object' then
      raise exception 'The cart has an invalid line.' using errcode = '22023';
    end if;
    begin
      v_id := (v_line->>'uniform_item_id')::uuid;
    exception when invalid_text_representation then
      v_id := null;
    end;
    v_size := nullif(v_line->>'size', '');
    if v_id is null or v_size is null then
      raise exception 'The cart has an invalid line.' using errcode = '22023';
    end if;
    v_raw := coalesce(v_line->'qty', '1'::jsonb)::text;
    if v_raw !~ '^[0-9]{1,3}$' then
      raise exception 'Each item can be 1 to 10 at a time.' using errcode = '22023';
    end if;
    v_qty := v_raw::int;
    if v_qty not between 1 and 10 then
      raise exception 'Each item can be 1 to 10 at a time.' using errcode = '22023';
    end if;

    v_n := 0;
    for i in 1 .. coalesce(array_length(v_ids, 1), 0) loop
      if v_ids[i] = v_id and v_sizes[i] = v_size then
        v_qtys[i] := v_qtys[i] + v_qty;
        v_n := i;
        exit;
      end if;
    end loop;
    if v_n = 0 then
      v_ids := v_ids || v_id;
      v_sizes := v_sizes || v_size;
      v_qtys := v_qtys || v_qty;
    end if;
  end loop;

  o_items := '[]'::jsonb;
  o_total_cents := 0;
  o_total_coins := 0;
  o_qty := 0;
  for i in 1 .. array_length(v_ids, 1) loop
    if v_qtys[i] > 10 then
      raise exception 'Each item can be 1 to 10 at a time.' using errcode = '22023';
    end if;
    select * into v_item from public.uniform_items where id = v_ids[i];
    if v_item.id is null or not v_item.active or v_item.location_id <> p_location then
      raise exception 'An item in the cart is no longer in the store. Refresh and try again.' using errcode = 'P0001';
    end if;
    v_found := false;
    v_stock := false;
    for sz in select * from jsonb_array_elements(v_item.sizes) loop
      if sz->>'label' = v_sizes[i] then
        v_found := true;
        v_stock := (sz->>'in_stock')::boolean;
        exit;
      end if;
    end loop;
    if not v_found then
      raise exception '% doesn''t come in size %.', v_item.name, v_sizes[i] using errcode = 'P0001';
    end if;
    if not v_stock then
      raise exception '% in size % is out of stock.', v_item.name, v_sizes[i] using errcode = 'P0001';
    end if;
    if p_coins and v_item.coin_cost is null then
      raise exception '% can''t be redeemed with coins.', v_item.name using errcode = 'P0001';
    end if;
    v_unit := case when p_coins then 0 else v_item.price_cents end;
    v_coin := case when p_coins then v_item.coin_cost end;
    o_items := o_items || jsonb_build_object(
      'uniform_item_id', v_item.id, 'name', v_item.name, 'size', v_sizes[i],
      'qty', v_qtys[i], 'unit_cents', v_unit, 'coin_cost', v_coin);
    o_total_cents := o_total_cents + v_unit * v_qtys[i];
    o_total_coins := o_total_coins + coalesce(v_coin, 0) * v_qtys[i];
    o_qty := o_qty + v_qtys[i];
  end loop;
end $$;

-- 7. Card order. p_lines: [{uniform_item_id, size, qty}]. The centre's UNIFORM_STORE_LOCATIONS gate
-- lives in the edge function (the env var lives there); everything data-related is enforced here.
create or replace function public.create_uniform_order(
  p_child uuid, p_lines jsonb, p_request_id uuid, p_expected_total_cents integer)
returns public.uniform_orders
language plpgsql
security definer
set search_path to 'public'
as $$
declare
  v_child public.children;
  v_order public.uniform_orders;
  b record;
begin
  if auth.uid() is null or p_request_id is null or not public.can_access_child(p_child) then
    raise exception 'not allowed' using errcode = '42501';
  end if;

  -- Serialise every order for this child. Taken BEFORE the request-id check so a concurrent double
  -- tap waits here and then finds the order the first tap committed.
  select * into v_child from public.children where id = p_child for update;

  select * into v_order from public.uniform_orders where request_id = p_request_id;
  if found then
    if v_order.child_id <> p_child or v_order.pay_method <> 'card' then
      raise exception 'not allowed' using errcode = '42501';
    end if;
    return v_order;
  end if;

  select * into b from public.uniform_build_lines(v_child.location_id, p_lines, false);
  if b.o_total_cents <= 0 then
    raise exception 'There is nothing to pay for in this order.' using errcode = '22023';
  end if;
  if p_expected_total_cents is distinct from b.o_total_cents then
    raise exception 'Prices changed while you were checking out: this order is now %. Review the cart again.',
      public.uniform_money(b.o_total_cents) using errcode = 'P0001';
  end if;

  begin
    insert into public.uniform_orders
      (child_id, location_id, items, pay_method, total_cents, coins_paid, status, request_id, free_qty,
       school_year, placed_by)
    values
      (p_child, v_child.location_id, b.o_items, 'card', b.o_total_cents, 0, 'awaiting_payment', p_request_id, 0,
       public.school_year_start(now()), auth.uid())
    returning * into v_order;
  exception when unique_violation then
    -- Same request id raced in from a different child's transaction.
    raise exception 'not allowed' using errcode = '42501';
  end;
  return v_order;
end $$;

-- 8. Stripe plumbing: service role only (EXECUTE revoked from every client role below).
create or replace function public.attach_uniform_session(p_order uuid, p_session text)
returns public.uniform_orders
language plpgsql
security definer
set search_path to 'public'
as $$
declare
  v_order public.uniform_orders;
begin
  if nullif(btrim(p_session), '') is null then
    raise exception 'A Stripe session id is required.' using errcode = '22023';
  end if;
  select * into v_order from public.uniform_orders where id = p_order for update;
  if v_order.id is null then
    raise exception 'Uniform order not found.' using errcode = 'P0002';
  end if;
  if v_order.stripe_session_id is not null then
    if v_order.stripe_session_id = p_session then return v_order; end if;
    raise exception 'That order already has a different Stripe session.' using errcode = 'P0001';
  end if;
  if v_order.pay_method <> 'card' or v_order.status <> 'awaiting_payment' then
    raise exception 'That order is not waiting for a card payment.' using errcode = 'P0001';
  end if;
  update public.uniform_orders set stripe_session_id = p_session where id = p_order returning * into v_order;
  return v_order;
end $$;

-- The webhook's only way to mark an order paid. Idempotent. The amount must equal the order total
-- (else it raises and the order is untouched - the edge function logs the failure). Bells fire only
-- on a real status change.
create or replace function public.mark_uniform_order_paid(
  p_session text, p_payment_intent text, p_amount_total_cents integer)
returns public.uniform_orders
language plpgsql
security definer
set search_path to 'public'
as $$
declare
  v_order public.uniform_orders;
  v_prior text;
  v_late boolean;
  v_child_name text;
begin
  select * into v_order from public.uniform_orders where stripe_session_id = p_session for update;
  if v_order.id is null then
    raise exception 'No uniform order for that Stripe session.' using errcode = 'P0002';
  end if;
  if v_order.status in ('paid', 'handed_over') then
    return v_order;
  end if;
  if p_amount_total_cents is distinct from v_order.total_cents then
    raise exception 'Stripe charged % cents but uniform order #% is % cents. Order left unpaid.',
      p_amount_total_cents, v_order.order_no, v_order.total_cents using errcode = 'P0001';
  end if;

  v_prior := v_order.status;
  v_late := v_prior in ('expired', 'cancelled');
  -- Money landed after the order was closed: never lose it. Record it as paid and flag it for staff.
  update public.uniform_orders
     set status = 'paid',
         paid_at = now(),
         stripe_payment_intent = coalesce(p_payment_intent, stripe_payment_intent),
         closed_by = null,
         closed_at = null,
         note = case when v_late
                     then coalesce(note || ' · ', '') || 'paid after expiry — needs review'
                     else note end
   where id = v_order.id
  returning * into v_order;

  select first_name into v_child_name from public.children where id = v_order.child_id;
  insert into public.notifications (profile_id, kind, title, body, link)
  select gp.profile_id, 'uniform', 'Uniform order #' || v_order.order_no || ' is paid',
    v_child_name || '''s ' || public.uniform_order_summary(v_order.items)
      || ' is ready for pickup at the center.',
    '/dashboard?view=uniform'
  from public.ghl_child_parents(v_order.child_id) gp;
  insert into public.notifications (profile_id, kind, title, body, link)
  select s.profile_id,
    'uniform',
    case when v_late then 'Uniform order #' || v_order.order_no || ' paid after it closed - needs review'
         else 'New uniform order #' || v_order.order_no end,
    v_child_name || ' - ' || public.uniform_order_summary(v_order.items) || ' (paid '
      || public.uniform_money(v_order.total_cents) || ' by card). '
      || case when v_late then 'The order had already ' || v_prior || '; check it in Rewards → Uniform orders.'
              else 'Hand it over from Rewards → Uniform orders.' end,
    null
  from public.coin_order_staff(v_order.child_id) s;
  return v_order;
end $$;

-- Idempotent: only an awaiting_payment order expires; anything else is returned as it is (a late
-- `expired` webhook after a payment must not undo it).
create or replace function public.expire_uniform_order(p_order uuid)
returns public.uniform_orders
language plpgsql
security definer
set search_path to 'public'
as $$
declare
  v_order public.uniform_orders;
begin
  update public.uniform_orders set status = 'expired', closed_at = now()
   where id = p_order and status = 'awaiting_payment'
  returning * into v_order;
  if not found then
    select * into v_order from public.uniform_orders where id = p_order;
    if v_order.id is null then
      raise exception 'Uniform order not found.' using errcode = 'P0002';
    end if;
  end if;
  return v_order;
end $$;

-- Housekeeping sweep: awaiting_payment older than p_hours -> expired. Returns the sessions so the
-- caller can expire them in Stripe too.
create or replace function public.sweep_stale_uniform_orders(p_hours integer default 24)
returns table(o_order_id uuid, o_session text)
language sql
security definer
set search_path to 'public'
as $$
  update public.uniform_orders u set status = 'expired', closed_at = now()
   where u.status = 'awaiting_payment' and u.placed_at < now() - make_interval(hours => p_hours)
  returning u.id, u.stripe_session_id;
$$;

-- 9. Free uniform with coins.
create or replace function public.redeem_uniform_with_coins(
  p_child uuid, p_lines jsonb, p_request_id uuid,
  p_override boolean default false, p_override_reason text default null)
returns public.uniform_orders
language plpgsql
security definer
set search_path to 'public'
as $$
declare
  c_cap constant int := 2;
  v_role text := coalesce(public.my_role()::text, '');
  v_staff boolean := v_role in ('staff', 'manager', 'admin');
  v_mgr boolean := v_role in ('manager', 'admin');
  v_override boolean := coalesce(p_override, false);
  v_reason text := left(nullif(btrim(p_override_reason), ''), 200);
  v_year int := public.school_year_start(now());
  v_child public.children;
  v_order public.uniform_orders;
  b record;
  v_used int;
  v_balance int;
  v_paid int;
  v_note text;
  v_tx uuid;
begin
  if auth.uid() is null or p_request_id is null or not public.can_access_child(p_child) then
    raise exception 'not allowed' using errcode = '42501';
  end if;
  if v_override and not v_mgr then
    raise exception 'not allowed' using errcode = '42501';
  end if;

  -- Same child lock the redemption floor takes; BEFORE the request-id check (see create_uniform_order).
  select * into v_child from public.children where id = p_child for update;

  select * into v_order from public.uniform_orders where request_id = p_request_id;
  if found then
    if v_order.child_id <> p_child or v_order.pay_method <> 'coins' then
      raise exception 'not allowed' using errcode = '42501';
    end if;
    return v_order;
  end if;

  if v_override and v_reason is null then
    raise exception 'Enter a reason to override.' using errcode = '22023';
  end if;

  select * into b from public.uniform_build_lines(v_child.location_id, p_lines, true);

  -- Cap: free items this child already holds this school year (cancelled / expired free a slot).
  select coalesce(sum(free_qty), 0) into v_used
    from public.uniform_orders
   where child_id = p_child and pay_method = 'coins' and school_year = v_year
     and status not in ('cancelled', 'expired');
  if v_used + b.o_qty > c_cap and not v_override then
    raise exception 'Only % free uniform items per school year — % has used %.', c_cap, v_child.first_name, v_used
      using errcode = 'P0001';
  end if;

  select coalesce(sum(amount), 0) into v_balance from public.coin_transactions where child_id = p_child;
  if v_balance >= b.o_total_coins then
    v_paid := b.o_total_coins;
  elsif v_override then
    v_paid := greatest(v_balance, 0);
    if v_paid = 0 then
      raise exception '% has no Blessing Coins, so there is nothing to spend. Award some first.', v_child.first_name
        using errcode = 'P0001';
    end if;
  else
    raise exception 'Not enough Blessing Coins: % has %, and this order costs %.', v_child.first_name, v_balance, b.o_total_coins
      using errcode = 'P0001';
  end if;

  if v_override then
    v_note := 'Manager override: ' || v_reason
      || case when v_paid < b.o_total_coins then ' (' || (b.o_total_coins - v_paid) || ' coins given without a balance)' else '' end;
  end if;

  begin
    insert into public.uniform_orders
      (child_id, location_id, items, pay_method, total_cents, coins_paid, status, request_id, free_qty,
       school_year, placed_by, paid_at, note)
    values
      (p_child, v_child.location_id, b.o_items, 'coins', 0, v_paid, 'paid', p_request_id, b.o_qty,
       v_year, auth.uid(), now(), v_note)
    returning * into v_order;
  exception when unique_violation then
    raise exception 'not allowed' using errcode = '42501';
  end;

  -- The ledger debit. coin_parent_notification rings the family's bell for this row ("spent N
  -- Blessing Coins on Uniform order #…"), so the family gets NO second uniform bell from here.
  insert into public.coin_transactions (child_id, location_id, kind, amount, reason_label, note, actor_id)
  values (p_child, v_child.location_id, 'redemption', -v_paid,
          left('Uniform order #' || v_order.order_no || ' · ' || public.uniform_order_summary(b.o_items), 200),
          v_note, auth.uid())
  returning id into v_tx;
  update public.uniform_orders set debit_tx_id = v_tx where id = v_order.id returning * into v_order;

  if not v_staff then
    insert into public.notifications (profile_id, kind, title, body, link)
    select s.profile_id, 'uniform', 'New free uniform order #' || v_order.order_no,
      v_child.first_name || ' - ' || public.uniform_order_summary(b.o_items) || ' (' || v_paid
        || ' coins). Hand it over from Rewards → Uniform orders.',
      null
    from public.coin_order_staff(p_child) s;
  end if;
  return v_order;
end $$;

-- 10. Hand-over: staff / manager / admin of that child's centre, once, only a paid order.
create or replace function public.hand_over_uniform_order(p_order uuid)
returns public.uniform_orders
language plpgsql
security definer
set search_path to 'public'
as $$
declare
  v_order public.uniform_orders;
begin
  select * into v_order from public.uniform_orders where id = p_order;
  if v_order.id is null
     or coalesce(public.my_role()::text, '') not in ('staff', 'manager', 'admin')
     or not public.can_access_child(v_order.child_id) then
    raise exception 'not allowed' using errcode = '42501';
  end if;

  update public.uniform_orders set status = 'handed_over', closed_by = auth.uid(), closed_at = now()
   where id = p_order and status = 'paid'
  returning * into v_order;
  if not found then
    select * into v_order from public.uniform_orders where id = p_order;
    raise exception '%', case v_order.status
      when 'awaiting_payment' then 'That order hasn''t been paid yet.'
      else 'That order was already handed over or cancelled.' end using errcode = 'P0001';
  end if;

  insert into public.notifications (profile_id, kind, title, body, link)
  select gp.profile_id, 'uniform', c.first_name || '''s uniform is handed over',
    c.first_name || ' got ' || public.uniform_order_summary(v_order.items) || ' (order #' || v_order.order_no || ').',
    '/dashboard?view=uniform'
  from public.ghl_child_parents(v_order.child_id) gp
  cross join public.children c
  where c.id = v_order.child_id;
  return v_order;
end $$;

-- 11. Cancel. A parent: only their own order, only while it can still be undone (a paid coins order
-- not yet handed over, or a card order still awaiting payment). Staff / manager: a paid order, with a
-- reason; a paid card order is refunded by hand in Stripe (the note says so). A handed-over order
-- can never be cancelled.
create or replace function public.cancel_uniform_order(p_order uuid, p_reason text default null)
returns public.uniform_orders
language plpgsql
security definer
set search_path to 'public'
as $$
declare
  v_order public.uniform_orders;
  v_staff boolean := coalesce(public.my_role()::text, '') in ('staff', 'manager', 'admin');
  v_reason text := left(nullif(btrim(p_reason), ''), 200);
  v_note text;
  v_tx uuid;
begin
  select * into v_order from public.uniform_orders where id = p_order;
  if v_order.id is null or auth.uid() is null or not public.can_access_child(v_order.child_id) then
    raise exception 'not allowed' using errcode = '42501';
  end if;
  -- Child lock first, then the order row (the order every function here uses; mark_uniform_order_paid
  -- takes only the order row, so there is no cycle).
  perform 1 from public.children where id = v_order.child_id for update;
  select * into v_order from public.uniform_orders where id = p_order for update;

  if v_order.status = 'handed_over' then
    raise exception 'A picked-up order can''t be cancelled.' using errcode = 'P0001';
  elsif v_order.status in ('cancelled', 'expired') then
    raise exception 'That order is already closed.' using errcode = 'P0001';
  end if;

  if v_staff then
    if v_reason is null then
      raise exception 'Enter a reason for the cancellation.' using errcode = '22023';
    end if;
    if v_order.status <> 'paid' then
      raise exception 'That order is still waiting for payment, so there is nothing to cancel yet.' using errcode = 'P0001';
    end if;
  else
    if v_order.placed_by <> auth.uid() then
      raise exception 'not allowed' using errcode = '42501';
    end if;
    if v_order.pay_method = 'card' and v_order.status = 'paid' then
      raise exception 'This order is paid. Ask the center to cancel it and refund your card.' using errcode = 'P0001';
    end if;
  end if;

  v_note := case when v_order.pay_method = 'card' and v_order.status = 'paid'
                 then coalesce(v_order.note || ' · ', '') || 'Cancelled by staff — refund the card payment manually in Stripe.'
                 else v_order.note end;
  update public.uniform_orders
     set status = 'cancelled', closed_by = auth.uid(), closed_at = now(), cancel_reason = v_reason, note = v_note
   where id = p_order
  returning * into v_order;

  -- Coins come back as a 'refund' ledger row (coin_parent_notification rings the family's bell).
  if v_order.pay_method = 'coins' and v_order.coins_paid > 0 then
    insert into public.coin_transactions (child_id, location_id, kind, amount, reason_label, note, actor_id)
    values (v_order.child_id, v_order.location_id, 'refund', v_order.coins_paid,
            'Refund · Uniform order #' || v_order.order_no, v_reason, auth.uid())
    returning id into v_tx;
    update public.uniform_orders set refund_tx_id = v_tx where id = p_order returning * into v_order;
  end if;

  if not v_staff then
    insert into public.notifications (profile_id, kind, title, body, link)
    select s.profile_id, 'uniform', 'Uniform order #' || v_order.order_no || ' cancelled',
      c.first_name || '''s family cancelled ' || public.uniform_order_summary(v_order.items)
        || case when v_order.pay_method = 'coins' then '. The coins went back.' else '.' end,
      null
    from public.coin_order_staff(v_order.child_id) s
    cross join public.children c
    where c.id = v_order.child_id;
  elsif v_order.pay_method = 'card' then
    -- (A coins order's family already got the refund bell from the ledger row.)
    insert into public.notifications (profile_id, kind, title, body, link)
    select gp.profile_id, 'uniform', 'Uniform order #' || v_order.order_no || ' cancelled',
      'The center cancelled ' || c.first_name || '''s ' || public.uniform_order_summary(v_order.items)
        || '. Your card will be refunded' || coalesce(' (' || v_reason || ')', '') || '.',
      '/dashboard?view=uniform'
    from public.ghl_child_parents(v_order.child_id) gp
    cross join public.children c
    where c.id = v_order.child_id;
  end if;
  return v_order;
end $$;

-- 12. Grants. Client RPCs: signed-in users only. Stripe plumbing: service role only. Helpers: nobody
-- (the definer functions above call them as their owner).
revoke all on function public.create_uniform_order(uuid, jsonb, uuid, integer) from public, anon;
revoke all on function public.redeem_uniform_with_coins(uuid, jsonb, uuid, boolean, text) from public, anon;
revoke all on function public.hand_over_uniform_order(uuid) from public, anon;
revoke all on function public.cancel_uniform_order(uuid, text) from public, anon;
grant execute on function public.create_uniform_order(uuid, jsonb, uuid, integer) to authenticated;
grant execute on function public.redeem_uniform_with_coins(uuid, jsonb, uuid, boolean, text) to authenticated;
grant execute on function public.hand_over_uniform_order(uuid) to authenticated;
grant execute on function public.cancel_uniform_order(uuid, text) to authenticated;

revoke all on function public.attach_uniform_session(uuid, text) from public, anon, authenticated;
revoke all on function public.mark_uniform_order_paid(text, text, integer) from public, anon, authenticated;
revoke all on function public.expire_uniform_order(uuid) from public, anon, authenticated;
revoke all on function public.sweep_stale_uniform_orders(integer) from public, anon, authenticated;
grant execute on function public.attach_uniform_session(uuid, text) to service_role;
grant execute on function public.mark_uniform_order_paid(text, text, integer) to service_role;
grant execute on function public.expire_uniform_order(uuid) to service_role;
grant execute on function public.sweep_stale_uniform_orders(integer) to service_role;

revoke all on function public.uniform_build_lines(uuid, jsonb, boolean) from public, anon, authenticated;
revoke all on function public.uniform_money(integer) from public, anon, authenticated;
revoke all on function public.uniform_order_summary(jsonb) from public, anon, authenticated;
-- school_year_start / uniform_sizes_valid stay callable: a CHECK constraint evaluates the latter as
-- the inserting manager, and both are pure.

-- 13. Seed: a placeholder shirt and pants per centre. The three real centres ship INACTIVE so no
-- family can buy a placeholder-priced item; the manager turns them on after setting real prices.
-- Only the QA Sandbox is live. Guarded on the centre existing; re-running adds nothing.
insert into public.uniform_items (location_id, name, kind, price_cents, coin_cost, sizes, active, sort)
select l.id, v.name, v.kind, v.price_cents, v.coin_cost,
       '[{"label":"2T","in_stock":true},{"label":"3T","in_stock":true},{"label":"4T","in_stock":true},{"label":"5","in_stock":true},{"label":"6","in_stock":true},{"label":"7","in_stock":true}]'::jsonb,
       (l.id = '99999999-9999-9999-9999-999999999999'), v.sort
from public.locations l
cross join (values
  ('Uniform Shirt', 'shirt', 1500, 150, 1),
  ('Uniform Pants', 'pants', 2000, 200, 2)
) as v(name, kind, price_cents, coin_cost, sort)
where l.id in ('11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222',
               '44444444-4444-4444-4444-444444444444', '99999999-9999-9999-9999-999999999999')
  and not exists (select 1 from public.uniform_items x where x.location_id = l.id and x.name = v.name);

-- 14. Hourly sweep. A checkout whose Stripe session creation/attach failed never gets a
-- checkout.session.expired webhook, so expire awaiting_payment orders older than 25 h here (Stripe's
-- own session lasts 24 h). Plain SQL, no vault / edge function, no notifications. No-op if pg_cron is absent.
do $cron$
begin
  if exists (select 1 from pg_extension where extname = 'pg_cron') then
    begin
      perform cron.unschedule('uniform-expire-stale');
    exception when others then null;
    end;
    perform cron.schedule('uniform-expire-stale', '5 * * * *', $job$select count(*) from public.sweep_stale_uniform_orders(25)$job$);
  end if;
end $cron$;
