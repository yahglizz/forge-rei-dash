-- Deltas applied on top of 202607120001_initial_schema.sql during the Supabase
-- cutover (2026-07-13). These are already live on project eqblpbeqothkpyqiafzs;
-- this file keeps the repo reproducible. Order matches the applied migrations:
--   harden_function_grants, align_schema_to_app,
--   management_reads_all_announcements, column_guards_and_policy_fixes.
-- The live initial migration folded the following features in. They are
-- declared here as well so a fresh database can replay the tracked files.

alter table public.messages
  add column if not exists reactions jsonb not null default '[]'::jsonb,
  add column if not exists attachment_path text;
alter table public.messages alter column body set default '';
alter table public.messages drop constraint if exists messages_body_check;

create or replace function public.notify_announcement_audience() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  insert into public.notifications (profile_id, kind, title, body, link)
  select p.id, 'announcement', new.title, left(new.body, 500), '/dashboard?view=announcements'
  from public.profiles p
  where p.location_id = new.location_id and p.active and p.id is distinct from new.author_id
    and (new.audience = 'everyone'
      or (new.audience = 'parents' and p.role = 'parent')
      or (new.audience = 'staff' and p.role in ('staff','manager','admin')));
  return new;
end $$;
drop trigger if exists announcement_audience_notification on public.announcements;
create trigger announcement_audience_notification after insert on public.announcements
for each row execute function public.notify_announcement_audience();

insert into storage.buckets (id, name, public)
values ('message-attachments', 'message-attachments', false)
on conflict (id) do nothing;
create policy "participants read thread attachments" on storage.objects for select to authenticated
using (bucket_id = 'message-attachments' and (storage.foldername(name))[1] = 'chat'
  and public.is_thread_participant(((storage.foldername(name))[2])::uuid));
create policy "participants upload thread attachments" on storage.objects for insert to authenticated
with check (bucket_id = 'message-attachments' and (storage.foldername(name))[1] = 'chat'
  and public.is_thread_participant(((storage.foldername(name))[2])::uuid));
create policy "participants leave threads" on public.thread_participants for delete
using (profile_id = auth.uid());

-- === harden_function_grants ===
create or replace function public.touch_updated_at() returns trigger
language plpgsql set search_path = public as $$
begin new.updated_at = now(); return new; end $$;
revoke execute on function public.touch_updated_at() from anon, authenticated, public;
revoke execute on function public.handle_new_user() from anon, authenticated, public;
revoke execute on function public.notify_incident_guardians() from anon, authenticated, public;
revoke execute on function public.notify_announcement_audience() from anon, authenticated, public;
revoke execute on function public.my_role() from anon, public;
revoke execute on function public.my_location() from anon, public;
revoke execute on function public.my_staff_id() from anon, public;
revoke execute on function public.can_access_child(uuid) from anon, public;
revoke execute on function public.is_thread_participant(uuid) from anon, public;

-- === align_schema_to_app ===
alter table public.children add column if not exists guardian_profile_id uuid references public.profiles(id) on delete set null;
alter table public.invoices drop constraint if exists invoices_guardian_id_fkey;
alter table public.invoices add constraint invoices_guardian_id_fkey foreign key (guardian_id) references public.profiles(id) on delete cascade;
alter table public.payment_methods drop constraint if exists payment_methods_guardian_id_fkey;
alter table public.payment_methods add constraint payment_methods_guardian_id_fkey foreign key (guardian_id) references public.profiles(id) on delete cascade;
alter table public.invoices add column if not exists payments jsonb not null default '[]'::jsonb;

create or replace function public.can_access_child(target_child uuid) returns boolean
language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from public.children c
    where c.id = target_child and c.location_id = public.my_location() and (
      public.my_role() in ('manager','admin')
      or (public.my_role() = 'parent' and (
        c.guardian_profile_id = auth.uid()
        or exists (select 1 from public.guardian_children gc join public.guardians g on g.id = gc.guardian_id where gc.child_id = c.id and g.profile_id = auth.uid())))
      or (public.my_role() = 'staff' and exists (select 1 from public.staff_classrooms sc where sc.staff_id = public.my_staff_id() and sc.classroom_id = c.classroom_id))
    ))
$$;

create or replace function public.notify_incident_guardians() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  insert into public.notifications (profile_id, kind, title, body, link)
  select c.guardian_profile_id, 'incident', 'Incident report for ' || c.first_name,
    'A care team member submitted an incident report. Please review it with the center.', null
  from public.children c where c.id = new.child_id and c.guardian_profile_id is not null;
  return new;
end $$;

drop policy if exists "profiles visible at location" on public.profiles;
create policy "profiles visible at location" on public.profiles for select using (id = auth.uid() or location_id = public.my_location());
drop policy if exists "family invoices read" on public.invoices;
create policy "family invoices read" on public.invoices for select using (guardian_id = auth.uid() or (public.my_role() in ('manager','admin') and location_id = public.my_location()));
drop policy if exists "family invoices update paid" on public.invoices;
create policy "family invoices update paid" on public.invoices for update using (guardian_id = auth.uid()) with check (guardian_id = auth.uid());
drop policy if exists "family payments read" on public.payments;
create policy "family payments read" on public.payments for select using (exists(select 1 from public.invoices i where i.id = invoice_id and (i.guardian_id = auth.uid() or public.my_role() in ('manager','admin'))));
drop policy if exists "family or management record payments" on public.payments;
create policy "family or management record payments" on public.payments for insert with check (exists(select 1 from public.invoices i where i.id = invoice_id and (i.guardian_id = auth.uid() or public.my_role() in ('manager','admin'))));
drop policy if exists "family methods read" on public.payment_methods;
create policy "family methods read" on public.payment_methods for select using (guardian_id = auth.uid() or public.my_role() in ('manager','admin'));
drop policy if exists "family manages methods" on public.payment_methods;
create policy "family manages methods" on public.payment_methods for all using (guardian_id = auth.uid()) with check (guardian_id = auth.uid());

drop policy if exists "participants read threads" on public.message_threads;
create policy "participants read threads" on public.message_threads for select using (public.is_thread_participant(id) or (public.my_role() in ('manager','admin') and location_id = public.my_location()));
drop policy if exists "participants read memberships" on public.thread_participants;
create policy "participants read memberships" on public.thread_participants for select using (public.is_thread_participant(thread_id) or public.my_role() in ('manager','admin'));
drop policy if exists "participants read messages" on public.messages;
create policy "participants read messages" on public.messages for select using (public.is_thread_participant(thread_id) or public.my_role() in ('manager','admin'));
drop policy if exists "participants send messages" on public.messages;
create policy "participants send messages" on public.messages for insert with check ((public.is_thread_participant(thread_id) or public.my_role() in ('manager','admin')) and sender_id = auth.uid());
drop policy if exists "participants react to messages" on public.messages;
create policy "participants react to messages" on public.messages for update using (public.is_thread_participant(thread_id) or public.my_role() in ('manager','admin')) with check (public.is_thread_participant(thread_id) or public.my_role() in ('manager','admin'));

do $$ declare t text; begin
  foreach t in array array['children','classrooms','invoices','payroll_records','staff_shifts','staff_members','staff_classrooms','staff_schedules','thread_participants','message_threads','incident_reports','photo_posts','profiles','payment_methods'] loop
    begin execute format('alter publication supabase_realtime add table public.%I', t); exception when duplicate_object then null; end;
  end loop; end $$;

-- === management_reads_all_announcements ===
drop policy if exists "audience announcements read" on public.announcements;
create policy "audience announcements read" on public.announcements for select using (
  location_id = public.my_location() and (
    public.my_role() in ('manager','admin') or audience = 'everyone'
    or (audience = 'parents' and public.my_role() = 'parent') or (audience = 'staff' and public.my_role() = 'staff')));

-- === column_guards_and_policy_fixes ===
-- (Column-level protection RLS cannot express — enforced by BEFORE UPDATE triggers.)
create or replace function public.guard_invoice_update() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if public.my_role() in ('manager','admin') then return new; end if;
  new.amount := old.amount; new.invoice_number := old.invoice_number; new.description := old.description;
  new.guardian_id := old.guardian_id; new.child_id := old.child_id; new.location_id := old.location_id;
  new.issued_on := old.issued_on; new.due_on := old.due_on;
  return new;
end $$;
drop trigger if exists invoice_update_guard on public.invoices;
create trigger invoice_update_guard before update on public.invoices for each row execute function public.guard_invoice_update();

create or replace function public.guard_message_update() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  new.body := old.body; new.sender_id := old.sender_id; new.thread_id := old.thread_id;
  new.attachment_path := old.attachment_path; new.created_at := old.created_at;
  return new;
end $$;
drop trigger if exists message_update_guard on public.messages;
create trigger message_update_guard before update on public.messages for each row execute function public.guard_message_update();

create or replace function public.guard_child_update() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if public.my_role() <> 'parent' then return new; end if;
  new.first_name := old.first_name; new.last_name := old.last_name; new.birth_date := old.birth_date;
  new.classroom_id := old.classroom_id; new.location_id := old.location_id; new.guardian_profile_id := old.guardian_profile_id;
  new.allergies := old.allergies; new.medical_notes := old.medical_notes; new.pickup_notes := old.pickup_notes; new.active := old.active;
  return new;
end $$;
drop trigger if exists child_update_guard on public.children;
create trigger child_update_guard before update on public.children for each row execute function public.guard_child_update();

drop policy if exists "creators update own threads" on public.message_threads;
create policy "participants update threads" on public.message_threads for update
using (public.is_thread_participant(id) or (public.my_role() in ('manager','admin') and location_id = public.my_location()))
with check (public.is_thread_participant(id) or (public.my_role() in ('manager','admin') and location_id = public.my_location()));

drop policy if exists "members create notifications" on public.notifications;
create policy "members create notifications" on public.notifications for insert with check (
  auth.uid() is not null and (
    profile_id = auth.uid()
    or exists (select 1 from public.thread_participants a join public.thread_participants b on a.thread_id = b.thread_id where a.profile_id = auth.uid() and b.profile_id = notifications.profile_id)
    or (public.my_role() in ('manager','admin') and exists (select 1 from public.profiles p where p.id = profile_id and p.location_id = public.my_location()))
    or (public.my_role() = 'parent' and exists (select 1 from public.profiles p where p.id = profile_id and p.role in ('manager','admin') and p.location_id = public.my_location()))
  ));

-- === guard_thread_rename ===
create or replace function public.guard_thread_update() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  new.location_id := old.location_id; new.kind := old.kind;
  new.created_by := old.created_by; new.created_at := old.created_at;
  return new;
end $$;
drop trigger if exists thread_update_guard on public.message_threads;
create trigger thread_update_guard before update on public.message_threads for each row execute function public.guard_thread_update();
revoke execute on function public.guard_thread_update() from anon, authenticated, public;
