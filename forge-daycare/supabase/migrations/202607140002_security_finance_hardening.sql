-- Security, tenant isolation, center settings, and normalized finance ledger.
-- Review and apply only after a live no-data schema/policy/function snapshot.

alter table public.classrooms add column if not exists active boolean not null default true;
alter table public.locations
  add column if not exists phone text,
  add column if not exists opens_at time,
  add column if not exists closes_at time;

alter table public.payments
  add column if not exists provider text not null default 'manual',
  add column if not exists status text not null default 'succeeded',
  add column if not exists provider_reference text,
  add column if not exists idempotency_key text,
  add column if not exists recorded_by uuid references public.profiles(id) on delete set null,
  add column if not exists created_at timestamptz not null default now();

alter table public.payroll_records add column if not exists payment_reference text;

do $$
begin
  if not exists (select 1 from pg_constraint where conrelid = 'public.payments'::regclass and conname = 'payments_provider_check') then
    alter table public.payments add constraint payments_provider_check
      check (provider in ('manual', 'stripe'));
  end if;
  if not exists (select 1 from pg_constraint where conrelid = 'public.payments'::regclass and conname = 'payments_status_check') then
    alter table public.payments add constraint payments_status_check
      check (status in ('pending', 'succeeded', 'failed', 'refunded', 'void'));
  end if;
end $$;

create unique index if not exists payments_idempotency_key_unique
  on public.payments (idempotency_key) where idempotency_key is not null;
create unique index if not exists payments_provider_reference_unique
  on public.payments (provider, provider_reference) where provider_reference is not null;
create index if not exists payments_invoice_paid_at_idx on public.payments (invoice_id, paid_at desc);

-- Convert the deprecated invoice JSON payment history into ledger rows. A
-- deterministic idempotency key makes this safe to rerun. Malformed entries are
-- ignored rather than aborting the migration.
insert into public.payments (
  invoice_id, amount, method_label, reference, paid_at, provider, status,
  idempotency_key, created_at
)
select
  i.id,
  case when (entry.value->>'amount') ~ '^[0-9]+(\.[0-9]+)?$'
    then (entry.value->>'amount')::numeric else i.amount end,
  coalesce(nullif(entry.value->>'method_label', ''), 'Legacy record'),
  nullif(entry.value->>'reference', ''),
  case when (entry.value->>'paid_at') ~ '^\d{4}-\d{2}-\d{2}T'
    then (entry.value->>'paid_at')::timestamptz else coalesce(i.paid_at, i.created_at) end,
  'manual', 'succeeded',
  'legacy-invoice-json:' || i.id::text || ':' || (entry.ordinality - 1)::text,
  i.created_at
from public.invoices i
cross join lateral jsonb_array_elements(
  case when jsonb_typeof(i.payments) = 'array' then i.payments else '[]'::jsonb end
) with ordinality as entry(value, ordinality)
on conflict (idempotency_key) where idempotency_key is not null do nothing;

comment on column public.invoices.payments is
  'DEPRECATED compatibility cache. public.payments is authoritative; do not write this column.';

-- A caller can update ordinary personal fields, but cannot self-promote,
-- transfer tenants, reactivate, or rewrite identity/permission fields.
create or replace function public.guard_profile_update() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if auth.uid() = old.id then
    new.id := old.id;
    new.location_id := old.location_id;
    new.role := old.role;
    new.login_id := old.login_id;
    new.auth_email := old.auth_email;
    new.active := old.active;
    new.permissions := old.permissions;
    new.created_at := old.created_at;
  elsif public.my_role() = 'manager' then
    new.id := old.id;
    new.location_id := old.location_id;
    new.role := old.role;
    new.login_id := old.login_id;
    new.auth_email := old.auth_email;
    new.permissions := old.permissions;
    new.created_at := old.created_at;
    if old.role in ('manager','admin') then new.active := old.active; end if;
  end if;
  return new;
end $$;

drop trigger if exists profile_update_guard on public.profiles;
create trigger profile_update_guard before update on public.profiles
for each row execute function public.guard_profile_update();

-- Constrain mutable membership rows to their identity columns. This prevents a
-- participant from moving their own membership to another user or thread.
create or replace function public.guard_thread_participant_update() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  new.thread_id := old.thread_id;
  new.profile_id := old.profile_id;
  return new;
end $$;

drop trigger if exists thread_participant_update_guard on public.thread_participants;
create trigger thread_participant_update_guard before update on public.thread_participants
for each row execute function public.guard_thread_participant_update();

create or replace function public.guard_message_thread_update() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  new.id := old.id;
  new.location_id := old.location_id;
  new.created_by := old.created_by;
  new.created_at := old.created_at;
  if public.my_role() not in ('manager','admin') then new.kind := old.kind; end if;
  return new;
end $$;

drop trigger if exists message_thread_update_guard on public.message_threads;
create trigger message_thread_update_guard before update on public.message_threads
for each row execute function public.guard_message_thread_update();

-- Public/role execution is never needed for trigger functions.
revoke execute on function public.touch_updated_at() from anon, authenticated, public;
revoke execute on function public.handle_new_user() from anon, authenticated, public;
revoke execute on function public.notify_incident_guardians() from anon, authenticated, public;
revoke execute on function public.notify_announcement_audience() from anon, authenticated, public;
revoke execute on function public.guard_invoice_update() from anon, authenticated, public;
revoke execute on function public.guard_message_update() from anon, authenticated, public;
revoke execute on function public.guard_child_update() from anon, authenticated, public;
revoke execute on function public.guard_profile_update() from anon, authenticated, public;
revoke execute on function public.guard_thread_participant_update() from anon, authenticated, public;
revoke execute on function public.guard_message_thread_update() from anon, authenticated, public;

-- Helper functions are intentional RLS primitives. Only authenticated callers
-- may execute them and each returns information scoped to auth.uid().
revoke execute on function public.my_role() from anon, public;
revoke execute on function public.my_location() from anon, public;
revoke execute on function public.my_staff_id() from anon, public;
revoke execute on function public.can_access_child(uuid) from anon, public;
revoke execute on function public.is_thread_participant(uuid) from anon, public;
grant execute on function public.my_role() to authenticated;
grant execute on function public.my_location() to authenticated;
grant execute on function public.my_staff_id() to authenticated;
grant execute on function public.can_access_child(uuid) to authenticated;
grant execute on function public.is_thread_participant(uuid) to authenticated;

-- Location-scoped management policies. Each nested relation validates the
-- tenant instead of trusting an unscoped manager/admin role check.
drop policy if exists "location members read location" on public.locations;
create policy "location members read location" on public.locations for select
using (id = public.my_location());
drop policy if exists "management updates location" on public.locations;
create policy "management updates location" on public.locations for update
using (public.my_role() in ('manager','admin') and id = public.my_location())
with check (public.my_role() in ('manager','admin') and id = public.my_location());

drop policy if exists "users update own basic profile" on public.profiles;
create policy "users update own basic profile" on public.profiles for update
using (id = auth.uid() and active)
with check (id = auth.uid() and location_id = public.my_location());
drop policy if exists "admin manages profiles" on public.profiles;
drop policy if exists "management manages profiles" on public.profiles;
create policy "management manages profiles" on public.profiles for update
using (public.my_role() in ('manager','admin') and location_id = public.my_location())
with check (public.my_role() in ('manager','admin') and location_id = public.my_location());

drop policy if exists "management manages guardians" on public.guardians;
create policy "management manages guardians" on public.guardians for update
using (public.my_role() in ('manager','admin') and location_id = public.my_location())
with check (
  public.my_role() in ('manager','admin') and location_id = public.my_location()
  and exists (select 1 from public.profiles p
    where p.id = guardians.profile_id and p.location_id = guardians.location_id and p.role = 'parent')
);

drop policy if exists "management manages children" on public.children;
create policy "management manages children" on public.children for update
using (public.my_role() in ('manager','admin') and location_id = public.my_location())
with check (
  public.my_role() in ('manager','admin') and location_id = public.my_location()
  and (classroom_id is null or exists (select 1 from public.classrooms c
    where c.id = children.classroom_id and c.location_id = children.location_id))
  and (guardian_profile_id is null or exists (select 1 from public.profiles p
    where p.id = children.guardian_profile_id and p.location_id = children.location_id and p.role = 'parent'))
);
drop policy if exists "management creates children" on public.children;
create policy "management creates children" on public.children for insert with check (
  public.my_role() in ('manager','admin') and location_id = public.my_location()
  and (classroom_id is null or exists (select 1 from public.classrooms c
    where c.id = children.classroom_id and c.location_id = children.location_id))
  and (guardian_profile_id is null or exists (select 1 from public.profiles p
    where p.id = children.guardian_profile_id and p.location_id = children.location_id and p.role = 'parent'))
);

drop policy if exists "management manages classrooms" on public.classrooms;
create policy "management manages classrooms" on public.classrooms for update
using (public.my_role() in ('manager','admin') and location_id = public.my_location())
with check (public.my_role() in ('manager','admin') and location_id = public.my_location());
drop policy if exists "management creates classrooms" on public.classrooms;
create policy "management creates classrooms" on public.classrooms for insert
with check (public.my_role() in ('manager','admin') and location_id = public.my_location());

drop policy if exists "admin manages assignments" on public.staff_classrooms;
drop policy if exists "management manages assignments" on public.staff_classrooms;
create policy "management manages assignments" on public.staff_classrooms for all
using (
  public.my_role() in ('manager','admin')
  and exists (select 1 from public.staff_members s where s.id = staff_id and s.location_id = public.my_location())
  and exists (select 1 from public.classrooms c where c.id = classroom_id and c.location_id = public.my_location())
)
with check (
  public.my_role() in ('manager','admin')
  and exists (select 1 from public.staff_members s where s.id = staff_id and s.location_id = public.my_location())
  and exists (select 1 from public.classrooms c where c.id = classroom_id and c.location_id = public.my_location())
);

drop policy if exists "admin manages staff" on public.staff_members;
drop policy if exists "management manages staff" on public.staff_members;
create policy "management manages staff" on public.staff_members for update
using (public.my_role() in ('manager','admin') and location_id = public.my_location())
with check (
  public.my_role() in ('manager','admin') and location_id = public.my_location()
  and exists (select 1 from public.profiles p where p.id = staff_members.profile_id
    and p.location_id = staff_members.location_id and p.role in ('staff','manager','admin'))
);

drop policy if exists "management manages guardian links" on public.guardian_children;
create policy "management manages guardian links" on public.guardian_children for all
using (
  public.my_role() in ('manager','admin')
  and exists (select 1 from public.guardians g where g.id = guardian_id and g.location_id = public.my_location())
  and exists (select 1 from public.children c where c.id = child_id and c.location_id = public.my_location())
)
with check (
  public.my_role() in ('manager','admin')
  and exists (select 1 from public.guardians g where g.id = guardian_id and g.location_id = public.my_location())
  and exists (select 1 from public.children c where c.id = child_id and c.location_id = public.my_location())
);

drop policy if exists "staff read own or management shifts" on public.staff_shifts;
create policy "staff read own or management shifts" on public.staff_shifts for select
using (
  staff_id = public.my_staff_id()
  or (public.my_role() in ('manager','admin') and exists (
    select 1 from public.staff_members s where s.id = staff_id and s.location_id = public.my_location()))
);
drop policy if exists "staff clock own shift" on public.staff_shifts;
create policy "staff clock own shift" on public.staff_shifts for insert with check (
  staff_id = public.my_staff_id()
  or (public.my_role() in ('manager','admin') and exists (
    select 1 from public.staff_members s where s.id = staff_id and s.location_id = public.my_location()))
);
drop policy if exists "staff close own shift" on public.staff_shifts;
create policy "staff close own shift" on public.staff_shifts for update using (
  staff_id = public.my_staff_id()
  or (public.my_role() in ('manager','admin') and exists (
    select 1 from public.staff_members s where s.id = staff_id and s.location_id = public.my_location()))
) with check (
  staff_id = public.my_staff_id()
  or (public.my_role() in ('manager','admin') and exists (
    select 1 from public.staff_members s where s.id = staff_id and s.location_id = public.my_location()))
);

drop policy if exists "authors or management update logs" on public.daily_logs;
create policy "authors or management update logs" on public.daily_logs for update
using (author_id = auth.uid() or (public.my_role() in ('manager','admin') and public.can_access_child(child_id)))
with check (author_id = auth.uid() or (public.my_role() in ('manager','admin') and public.can_access_child(child_id)));

drop policy if exists "thread creators add participants" on public.thread_participants;
create policy "thread creators add participants" on public.thread_participants for insert
with check (
  exists (
    select 1 from public.message_threads t
    join public.profiles p on p.id = thread_participants.profile_id
    where t.id = thread_participants.thread_id
      and t.location_id = public.my_location()
      and p.location_id = t.location_id
      and p.active
      and (t.created_by = auth.uid() or public.my_role() in ('manager','admin'))
  )
);
drop policy if exists "participants update read time" on public.thread_participants;
create policy "participants update read time" on public.thread_participants for update
using (profile_id = auth.uid()) with check (profile_id = auth.uid());

drop policy if exists "participants read memberships" on public.thread_participants;
create policy "participants read memberships" on public.thread_participants for select using (
  public.is_thread_participant(thread_id)
  or (public.my_role() in ('manager','admin') and exists (
    select 1 from public.message_threads t where t.id = thread_id and t.location_id = public.my_location()))
);
drop policy if exists "participants read messages" on public.messages;
create policy "participants read messages" on public.messages for select using (
  public.is_thread_participant(thread_id)
  or (public.my_role() in ('manager','admin') and exists (
    select 1 from public.message_threads t where t.id = thread_id and t.location_id = public.my_location()))
);
drop policy if exists "participants send messages" on public.messages;
create policy "participants send messages" on public.messages for insert with check (
  sender_id = auth.uid() and (
    public.is_thread_participant(thread_id)
    or (public.my_role() in ('manager','admin') and exists (
      select 1 from public.message_threads t where t.id = thread_id and t.location_id = public.my_location()))
  )
);
drop policy if exists "participants react to messages" on public.messages;
create policy "participants react to messages" on public.messages for update using (
  public.is_thread_participant(thread_id)
  or (public.my_role() in ('manager','admin') and exists (
    select 1 from public.message_threads t where t.id = thread_id and t.location_id = public.my_location()))
) with check (
  public.is_thread_participant(thread_id)
  or (public.my_role() in ('manager','admin') and exists (
    select 1 from public.message_threads t where t.id = thread_id and t.location_id = public.my_location()))
);

drop policy if exists "family payments read" on public.payments;
create policy "family payments read" on public.payments for select using (
  exists (
    select 1 from public.invoices i
    where i.id = invoice_id and i.location_id = public.my_location()
      and (i.guardian_id = auth.uid() or public.my_role() in ('manager','admin'))
  )
);
drop policy if exists "management records payments" on public.payments;
drop policy if exists "family or management record payments" on public.payments;
-- Ledger inserts are only allowed through record_invoice_payment(), which
-- atomically authorizes, inserts, and updates the invoice.

drop policy if exists "family invoices update paid" on public.invoices;
drop policy if exists "management manages invoices" on public.invoices;
create policy "management manages invoices" on public.invoices for update
using (public.my_role() in ('manager','admin') and location_id = public.my_location())
with check (
  public.my_role() in ('manager','admin') and location_id = public.my_location()
  and exists (select 1 from public.profiles p where p.id = invoices.guardian_id
    and p.location_id = invoices.location_id and p.role = 'parent')
  and (child_id is null or exists (select 1 from public.children c
    where c.id = invoices.child_id and c.location_id = invoices.location_id))
);
drop policy if exists "management creates invoices" on public.invoices;
create policy "management creates invoices" on public.invoices for insert with check (
  public.my_role() in ('manager','admin') and location_id = public.my_location()
  and exists (select 1 from public.profiles p where p.id = invoices.guardian_id
    and p.location_id = invoices.location_id and p.role = 'parent')
  and (child_id is null or exists (select 1 from public.children c
    where c.id = invoices.child_id and c.location_id = invoices.location_id))
);

drop policy if exists "family methods read" on public.payment_methods;
create policy "family methods read" on public.payment_methods for select using (
  exists (select 1 from public.profiles p where p.id = guardian_id and p.location_id = public.my_location())
  and (guardian_id = auth.uid() or public.my_role() in ('manager','admin'))
);
drop policy if exists "family manages methods" on public.payment_methods;
create policy "family manages methods" on public.payment_methods for all
using (guardian_id = auth.uid() and exists (
  select 1 from public.profiles p where p.id = guardian_id and p.location_id = public.my_location()))
with check (guardian_id = auth.uid() and exists (
  select 1 from public.profiles p where p.id = guardian_id and p.location_id = public.my_location()));

drop policy if exists "staff own payroll admin all" on public.payroll_records;
drop policy if exists "staff own payroll or management at location" on public.payroll_records;
create policy "staff own payroll or management at location" on public.payroll_records for select using (
  staff_id = public.my_staff_id()
  or (public.my_role() in ('manager','admin') and exists (
    select 1 from public.staff_members s where s.id = staff_id and s.location_id = public.my_location()))
);
drop policy if exists "admin manages payroll" on public.payroll_records;
drop policy if exists "management manages payroll at location" on public.payroll_records;
create policy "management manages payroll at location" on public.payroll_records for update
using (public.my_role() in ('manager','admin') and exists (
  select 1 from public.staff_members s where s.id = staff_id and s.location_id = public.my_location()))
with check (public.my_role() in ('manager','admin') and exists (
  select 1 from public.staff_members s where s.id = staff_id and s.location_id = public.my_location()));
drop policy if exists "management creates payroll at location" on public.payroll_records;
create policy "management creates payroll at location" on public.payroll_records for insert
with check (public.my_role() in ('manager','admin') and exists (
  select 1 from public.staff_members s where s.id = staff_id and s.location_id = public.my_location()));

drop policy if exists "admin manages schedules" on public.staff_schedules;
drop policy if exists "management manages schedules" on public.staff_schedules;
create policy "management manages schedules" on public.staff_schedules for all
using (public.my_role() in ('manager','admin') and exists (
  select 1 from public.staff_members s where s.id = staff_id and s.location_id = public.my_location()))
with check (public.my_role() in ('manager','admin') and exists (
  select 1 from public.staff_members s where s.id = staff_id and s.location_id = public.my_location()));

drop policy if exists "educators post photos" on public.photo_posts;
create policy "educators post photos" on public.photo_posts for insert with check (
  public.my_role() in ('staff','manager','admin')
  and public.can_access_child(child_id)
  and uploaded_by = auth.uid()
);
drop policy if exists "families post linked child photos" on public.photo_posts;
create policy "families post linked child photos" on public.photo_posts for insert with check (
  public.my_role() = 'parent'
  and public.can_access_child(child_id)
  and uploaded_by = auth.uid()
);

-- Storage paths are part of the authorization boundary.
drop policy if exists "authenticated avatar reads" on storage.objects;
drop policy if exists "location avatar reads" on storage.objects;
create policy "location avatar reads" on storage.objects for select to authenticated
using (
  bucket_id = 'avatars'
  and exists (
    select 1 from public.profiles p
    where p.id::text = (storage.foldername(name))[1]
      and (p.id = auth.uid() or p.location_id = public.my_location())
  )
);
drop policy if exists "educators upload child photos" on storage.objects;
create policy "educators upload child photos" on storage.objects for insert to authenticated
with check (
  bucket_id = 'child-photos'
  and public.my_role() in ('staff','manager','admin')
  and public.can_access_child(((storage.foldername(name))[1])::uuid)
);
drop policy if exists "participants read thread attachments" on storage.objects;
drop policy if exists "thread attachment reads" on storage.objects;
create policy "thread attachment reads" on storage.objects for select to authenticated
using (
  bucket_id = 'message-attachments'
  and (storage.foldername(name))[1] = 'chat'
  and (
    public.is_thread_participant(((storage.foldername(name))[2])::uuid)
    or (public.my_role() in ('manager','admin') and exists (
      select 1 from public.message_threads t
      where t.id = ((storage.foldername(name))[2])::uuid and t.location_id = public.my_location()))
  )
);
drop policy if exists "participants upload thread attachments" on storage.objects;
drop policy if exists "thread attachment uploads" on storage.objects;
create policy "thread attachment uploads" on storage.objects for insert to authenticated
with check (
  bucket_id = 'message-attachments'
  and (storage.foldername(name))[1] = 'chat'
  and (
    public.is_thread_participant(((storage.foldername(name))[2])::uuid)
    or (public.my_role() in ('manager','admin') and exists (
      select 1 from public.message_threads t
      where t.id = ((storage.foldername(name))[2])::uuid and t.location_id = public.my_location()))
  )
);

-- Transaction-safe invoice payment operation. The ledger insert and invoice
-- status update commit together. Idempotent retries return the first row.
create or replace function public.record_invoice_payment(
  p_invoice_id uuid,
  p_amount numeric,
  p_method_label text,
  p_reference text default null,
  p_paid_at timestamptz default now(),
  p_provider text default 'manual',
  p_provider_reference text default null,
  p_idempotency_key text default null
) returns public.payments
language plpgsql security definer set search_path = public as $$
declare
  v_invoice public.invoices;
  v_payment public.payments;
  v_total numeric;
begin
  if auth.uid() is null then raise exception 'authentication required' using errcode = '42501'; end if;
  if p_amount is null or p_amount <= 0 then
    raise exception 'payment amount must be positive' using errcode = '22023';
  end if;
  if nullif(trim(p_method_label), '') is null then
    raise exception 'payment method is required' using errcode = '22023';
  end if;

  select * into v_invoice from public.invoices
  where id = p_invoice_id and location_id = public.my_location()
  for update;
  if not found then raise exception 'invoice not found' using errcode = 'P0002'; end if;
  if public.my_role() not in ('manager','admin') and v_invoice.guardian_id <> auth.uid() then
    raise exception 'invoice authorization required' using errcode = '42501';
  end if;
  if public.my_role() not in ('manager','admin')
    and (coalesce(p_provider, 'manual') <> 'manual' or p_provider_reference is not null) then
    raise exception 'families may only create manual payment records' using errcode = '42501';
  end if;
  if v_invoice.status = 'void' then raise exception 'void invoices cannot be paid' using errcode = '22023'; end if;

  if p_idempotency_key is not null then
    select * into v_payment from public.payments where idempotency_key = p_idempotency_key;
    if found then
      if v_payment.invoice_id <> p_invoice_id then
        raise exception 'idempotency key already used' using errcode = '23505';
      end if;
      return v_payment;
    end if;
  end if;

  insert into public.payments (
    invoice_id, amount, method_label, reference, paid_at, provider, status,
    provider_reference, idempotency_key, recorded_by
  ) values (
    p_invoice_id, p_amount, trim(p_method_label), nullif(trim(p_reference), ''),
    coalesce(p_paid_at, now()), coalesce(nullif(trim(p_provider), ''), 'manual'),
    'succeeded', nullif(trim(p_provider_reference), ''), p_idempotency_key, auth.uid()
  ) returning * into v_payment;

  select coalesce(sum(amount), 0) into v_total from public.payments
  where invoice_id = p_invoice_id and status = 'succeeded';
  if public.my_role() = 'parent' and v_total < v_invoice.amount then
    raise exception 'parent payment record must cover the invoice' using errcode = '22023';
  end if;

  update public.invoices set
    status = case when v_total >= amount then 'paid'::public.invoice_status else status end,
    paid_at = case when v_total >= amount then coalesce(p_paid_at, now()) else paid_at end
  where id = p_invoice_id;

  return v_payment;
exception when unique_violation then
  if p_idempotency_key is not null then
    select * into v_payment from public.payments where idempotency_key = p_idempotency_key;
    if found and v_payment.invoice_id = p_invoice_id then return v_payment; end if;
  end if;
  raise;
end $$;

create or replace function public.mark_payroll_paid(
  p_payroll_id uuid,
  p_paid_at timestamptz default now(),
  p_reference text default null
) returns public.payroll_records
language plpgsql security definer set search_path = public as $$
declare v_record public.payroll_records;
begin
  if auth.uid() is null or public.my_role() not in ('manager','admin') then
    raise exception 'management authorization required' using errcode = '42501';
  end if;
  select pr.* into v_record
  from public.payroll_records pr
  join public.staff_members s on s.id = pr.staff_id
  where pr.id = p_payroll_id and s.location_id = public.my_location()
  for update of pr;
  if not found then raise exception 'payroll record not found' using errcode = 'P0002'; end if;

  update public.payroll_records set
    status = 'paid',
    paid_at = coalesce(p_paid_at, now()),
    payment_reference = coalesce(nullif(trim(p_reference), ''), payment_reference)
  where id = p_payroll_id
  returning * into v_record;
  return v_record;
end $$;

revoke execute on function public.record_invoice_payment(uuid,numeric,text,text,timestamptz,text,text,text) from anon, public;
revoke execute on function public.mark_payroll_paid(uuid,timestamptz,text) from anon, public;
grant execute on function public.record_invoice_payment(uuid,numeric,text,text,timestamptz,text,text,text) to authenticated;
grant execute on function public.mark_payroll_paid(uuid,timestamptz,text) to authenticated;

-- Race-safe Login ID allocator for provision-user. Location is derived from the
-- authenticated caller; no service-role-provided tenant is accepted.
create table if not exists public.login_id_counters (
  account_kind text primary key,
  next_number bigint not null check (next_number > 0)
);
alter table public.login_id_counters enable row level security;

create or replace function public.allocate_login_id(p_role public.app_role) returns text
language plpgsql security definer set search_path = public as $$
declare
  v_kind text;
  v_prefix text;
  v_number bigint;
  v_candidate text;
begin
  if auth.uid() is null or public.my_role() not in ('manager','admin') then
    raise exception 'management authorization required' using errcode = '42501';
  end if;
  if p_role in ('manager','admin') and public.my_role() <> 'admin' then
    raise exception 'only admins may provision management accounts' using errcode = '42501';
  end if;
  v_kind := p_role::text;
  v_prefix := case p_role when 'parent' then 'PAR' when 'staff' then 'STF' when 'manager' then 'MGR' else 'ADM' end;
  loop
    insert into public.login_id_counters(account_kind, next_number)
      values (v_kind, 100001)
    on conflict (account_kind) do update
      set next_number = public.login_id_counters.next_number + 1
    returning next_number into v_number;
    v_candidate := 'BL-' || v_prefix || '-' || lpad(v_number::text, 6, '0');
    exit when not exists (select 1 from public.profiles where login_id = v_candidate);
  end loop;
  return v_candidate;
end $$;

revoke all on public.login_id_counters from anon, authenticated;
revoke execute on function public.allocate_login_id(public.app_role) from anon, public;
grant execute on function public.allocate_login_id(public.app_role) to authenticated;

do $$
begin
  alter publication supabase_realtime add table public.payments;
exception when duplicate_object then null;
end $$;
