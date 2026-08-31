-- Blessing Coins: enforce the "never negative" promise in the database.
--
-- The redeem dialog tells staff, in words, that allowing an over-budget
-- redemption "will spend everything they have and floor their balance at 0
-- (never negative)". Until now that floor lived only in the browser
-- (lib/coins.ts childCoinBalance() + RedeemModal), so two staff phones that
-- both read the same balance could both redeem against it. Proven against the
-- live DB in a rolled-back transaction: balance 20, two 15-coin redemptions,
-- both accepted, final balance -10.
--
-- The floor now lives here, so every current and future write path inherits it.
--
-- Deliberately scoped to kind = 'redemption'. An 'adjustment' is a manager
-- correcting an over-award and IS allowed to go negative — that is the whole
-- point of the correction mechanism.

create or replace function public.clamp_coin_redemption() returns trigger
language plpgsql security definer set search_path = public as $$
declare
  available integer;
begin
  if new.kind <> 'redemption' then
    return new;
  end if;

  -- Serialize redemptions per child. Without this lock two concurrent
  -- transactions each read the same pre-spend balance and each clamp to it,
  -- which is exactly the double-spend this trigger exists to stop.
  perform 1 from public.children where id = new.child_id for update;

  select coalesce(sum(amount), 0) into available
  from public.coin_transactions where child_id = new.child_id;

  if available <= 0 then
    raise exception 'Not enough Blessing Coins: balance is %', available
      using errcode = 'check_violation';
  end if;

  -- Spend at most what the child actually has. amount is negative for a
  -- redemption, so the floor is -available.
  if new.amount < -available then
    new.amount := -available;
  end if;

  return new;
end $$;

create trigger coin_redemption_floor before insert on public.coin_transactions
for each row execute function public.clamp_coin_redemption();

revoke execute on function public.clamp_coin_redemption() from public, anon, authenticated;
