-- Blessing Coins: positive-reinforcement reward system (spec:
-- docs/superpowers/specs/2026-07-17-blessing-coins-design.md).
-- Ledger table + store catalog. Balance is always SUM(amount) over the
-- ledger — never stored. The ledger is immutable: no update/delete policies;
-- mistakes are corrected with a new 'adjustment' row.

create table public.coin_transactions (
  id uuid primary key default gen_random_uuid(),
  child_id uuid not null references public.children(id) on delete cascade,
  location_id uuid not null references public.locations(id),
  kind text not null check (kind in ('award', 'redemption', 'adjustment')),
  amount integer not null check (amount <> 0),
  reason_label text not null,
  note text,
  reward_item_id uuid,
  actor_id uuid not null references public.profiles(id),
  created_at timestamptz not null default now(),
  -- Awards credit, redemptions debit; adjustments go either way but must say why.
  constraint award_positive check (kind <> 'award' or amount > 0),
  constraint redemption_negative check (kind <> 'redemption' or amount < 0),
  constraint adjustment_needs_note check (kind <> 'adjustment' or note is not null)
);

create table public.reward_items (
  id uuid primary key default gen_random_uuid(),
  location_id uuid not null references public.locations(id),
  name text not null,
  description text,
  cost integer not null check (cost > 0),
  icon text,
  active boolean not null default true,
  created_at timestamptz not null default now()
);

alter table public.coin_transactions
  add constraint coin_transactions_reward_item_fk
  foreign key (reward_item_id) references public.reward_items(id);

create index coin_transactions_child on public.coin_transactions (child_id, created_at desc);
create index reward_items_location on public.reward_items (location_id) where active;

alter table public.coin_transactions enable row level security;
alter table public.reward_items enable row level security;

-- Reads: same scoping as daily_logs/behavior — parents their children, staff
-- their classrooms, management the location.
create policy "scoped coin read" on public.coin_transactions
  for select using (public.can_access_child(child_id));

-- Staff award and redeem for children they can access; only management can
-- write adjustments (the correction mechanism). Nobody edits history.
create policy "staff award and redeem" on public.coin_transactions
  for insert with check (
    public.my_role() in ('staff', 'manager', 'admin')
    and kind in ('award', 'redemption')
    and public.can_access_child(child_id)
    and actor_id = auth.uid()
  );
create policy "management adjusts" on public.coin_transactions
  for insert with check (
    public.my_role() in ('manager', 'admin')
    and kind = 'adjustment'
    and location_id = public.my_location()
    and actor_id = auth.uid()
  );

-- Catalog: everyone at the location sees active items (parents get a read-only
-- storefront); management also sees retired ones so they can reactivate.
create policy "active catalog visible" on public.reward_items
  for select using (location_id = public.my_location() and (active or public.my_role() in ('manager', 'admin')));
create policy "management manages catalog" on public.reward_items
  for insert with check (public.my_role() in ('manager', 'admin') and location_id = public.my_location());
create policy "management updates catalog" on public.reward_items
  for update using (public.my_role() in ('manager', 'admin') and location_id = public.my_location())
  with check (public.my_role() in ('manager', 'admin') and location_id = public.my_location());
-- No delete policy: items are retired via active=false, preserving history.

-- Parents get a bell notification for every coin event on their child.
create or replace function public.notify_coin_transaction_guardian() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  insert into public.notifications (profile_id, kind, title, body, link)
  select g.profile_id, 'coins',
    case when new.amount >= 0
      then c.first_name || ' earned ' || new.amount || ' Blessing Coins!'
      else c.first_name || ' redeemed a reward' end,
    case when new.amount >= 0
      then c.first_name || ' was awarded +' || new.amount || ' for ' || new.reason_label || '.'
      else c.first_name || ' spent ' || abs(new.amount) || ' Blessing Coins on ' || new.reason_label || '.' end,
    '/dashboard?view=coins'
  from public.guardian_children gc
  join public.guardians g on g.id = gc.guardian_id
  join public.children c on c.id = gc.child_id
  where gc.child_id = new.child_id;
  return new;
end $$;
create trigger coin_parent_notification after insert on public.coin_transactions
for each row execute function public.notify_coin_transaction_guardian();

-- Starter catalog (spec §6) — placeholders management edits in-app. Seeded for
-- EVERY location so any center opens with a working store; the cross join keeps
-- this independent of any hardcoded location id.
insert into public.reward_items (location_id, name, description, cost, icon)
select l.id, x.name, x.description, x.cost, x.icon
from public.locations l
cross join (values
  ('Bag of Chips', 'A crunchy snack', 15, 'Popcorn'),
  ('Juice / Cold Drink', 'Pick a cold drink', 15, 'CupSoda'),
  ('Candy', 'A sweet treat', 20, 'Candy'),
  ('Cookies', 'Fresh-baked cookies', 20, 'Cookie'),
  ('Ice Cream Treat', 'A frozen treat', 30, 'IceCreamCone'),
  ('Lunch on Teacher', 'Your teacher treats you to lunch', 60, 'Sandwich'),
  ('Pizza Party Contribution', 'Counts toward the next class pizza party', 100, 'Pizza')
) as x(name, description, cost, icon);

do $$
begin
  alter publication supabase_realtime add table public.coin_transactions;
exception when duplicate_object then null;
end $$;
do $$
begin
  alter publication supabase_realtime add table public.reward_items;
exception when duplicate_object then null;
end $$;
