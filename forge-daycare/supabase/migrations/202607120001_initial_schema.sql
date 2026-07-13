-- A Touch of Blessings platform schema
-- Apply with: supabase db push (or paste into the Supabase SQL editor).

create extension if not exists pgcrypto;

create type public.app_role as enum ('parent', 'staff', 'manager', 'admin');
create type public.attendance_status as enum ('present', 'completed');
create type public.audience_type as enum ('everyone', 'parents', 'staff');
create type public.invoice_status as enum ('draft', 'due', 'paid', 'void', 'overdue');
create type public.incident_severity as enum ('minor', 'moderate', 'serious');

create table public.locations (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  address text,
  timezone text not null default 'America/New_York',
  created_at timestamptz not null default now()
);

create table public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  location_id uuid references public.locations(id) on delete set null,
  role public.app_role not null default 'parent',
  first_name text not null default '',
  last_name text not null default '',
  display_name text generated always as (trim(first_name || ' ' || last_name)) stored,
  avatar_path text,
  login_id text unique,
  auth_email text unique,
  phone text,
  active boolean not null default true,
  permissions jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.classrooms (
  id uuid primary key default gen_random_uuid(),
  location_id uuid not null references public.locations(id) on delete cascade,
  name text not null,
  age_group text not null,
  capacity integer not null check (capacity > 0),
  ratio_children integer not null default 6 check (ratio_children > 0),
  color text not null default '#5B2C8E',
  active boolean not null default true,
  unique (location_id, name)
);

create table public.guardians (
  id uuid primary key default gen_random_uuid(),
  profile_id uuid unique not null references public.profiles(id) on delete cascade,
  location_id uuid not null references public.locations(id) on delete cascade,
  relationship_label text default 'Parent',
  emergency_contact boolean not null default true,
  authorized_pickup boolean not null default true
);

create table public.staff_members (
  id uuid primary key default gen_random_uuid(),
  profile_id uuid unique not null references public.profiles(id) on delete cascade,
  location_id uuid not null references public.locations(id) on delete cascade,
  job_title text not null,
  hourly_rate numeric(10,2),
  hire_date date,
  certifications jsonb not null default '[]'::jsonb,
  color text not null default '#EDE4F5'
);

create table public.staff_classrooms (
  staff_id uuid not null references public.staff_members(id) on delete cascade,
  classroom_id uuid not null references public.classrooms(id) on delete cascade,
  primary key (staff_id, classroom_id)
);

create table public.children (
  id uuid primary key default gen_random_uuid(),
  location_id uuid not null references public.locations(id) on delete cascade,
  classroom_id uuid references public.classrooms(id) on delete set null,
  first_name text not null,
  last_name text not null,
  preferred_name text,
  birth_date date not null,
  avatar_path text,
  allergies text,
  medical_notes text,
  pickup_notes text,
  enrollment_date date not null default current_date,
  active boolean not null default true,
  created_at timestamptz not null default now()
);

create table public.guardian_children (
  guardian_id uuid not null references public.guardians(id) on delete cascade,
  child_id uuid not null references public.children(id) on delete cascade,
  primary_guardian boolean not null default false,
  primary key (guardian_id, child_id)
);

create table public.attendance (
  id uuid primary key default gen_random_uuid(),
  child_id uuid not null references public.children(id) on delete cascade,
  attendance_date date not null default current_date,
  checked_in_at timestamptz not null default now(),
  checked_out_at timestamptz,
  checked_in_by uuid references public.profiles(id) on delete set null,
  checked_out_by uuid references public.profiles(id) on delete set null,
  status public.attendance_status not null default 'present',
  notes text,
  unique (child_id, attendance_date)
);

create table public.staff_shifts (
  id uuid primary key default gen_random_uuid(),
  staff_id uuid not null references public.staff_members(id) on delete cascade,
  clocked_in_at timestamptz not null default now(),
  clocked_out_at timestamptz,
  notes text,
  created_at timestamptz not null default now()
);

create table public.daily_logs (
  id uuid primary key default gen_random_uuid(),
  child_id uuid not null references public.children(id) on delete cascade,
  author_id uuid references public.profiles(id) on delete set null,
  log_date date not null default current_date,
  activity text,
  mood text,
  meal text,
  nap_minutes integer,
  bathroom text,
  notes text,
  occurred_at timestamptz not null default now(),
  created_at timestamptz not null default now()
);

create table public.photo_posts (
  id uuid primary key default gen_random_uuid(),
  child_id uuid not null references public.children(id) on delete cascade,
  uploaded_by uuid references public.profiles(id) on delete set null,
  storage_path text not null,
  caption text,
  taken_at timestamptz not null default now(),
  created_at timestamptz not null default now()
);

create table public.announcements (
  id uuid primary key default gen_random_uuid(),
  location_id uuid not null references public.locations(id) on delete cascade,
  author_id uuid references public.profiles(id) on delete set null,
  audience public.audience_type not null,
  title text not null,
  body text not null,
  pinned boolean not null default false,
  published_at timestamptz not null default now(),
  expires_at timestamptz
);

create table public.incident_reports (
  id uuid primary key default gen_random_uuid(),
  child_id uuid not null references public.children(id) on delete cascade,
  reporter_id uuid references public.profiles(id) on delete set null,
  occurred_at timestamptz not null,
  location_detail text not null,
  severity public.incident_severity not null,
  description text not null,
  action_taken text not null,
  witness_names text,
  parent_notified_at timestamptz not null default now(),
  created_at timestamptz not null default now()
);

create table public.notifications (
  id uuid primary key default gen_random_uuid(),
  profile_id uuid not null references public.profiles(id) on delete cascade,
  kind text not null,
  title text not null,
  body text not null,
  link text,
  read_at timestamptz,
  created_at timestamptz not null default now()
);

create table public.message_threads (
  id uuid primary key default gen_random_uuid(),
  location_id uuid not null references public.locations(id) on delete cascade,
  title text,
  kind text not null default 'direct' check (kind in ('direct', 'group', 'broadcast')),
  created_by uuid references public.profiles(id) on delete set null,
  created_at timestamptz not null default now()
);

create table public.thread_participants (
  thread_id uuid not null references public.message_threads(id) on delete cascade,
  profile_id uuid not null references public.profiles(id) on delete cascade,
  last_read_at timestamptz,
  primary key (thread_id, profile_id)
);

create table public.messages (
  id uuid primary key default gen_random_uuid(),
  thread_id uuid not null references public.message_threads(id) on delete cascade,
  sender_id uuid references public.profiles(id) on delete set null,
  body text not null check (length(body) between 1 and 4000),
  created_at timestamptz not null default now()
);

create table public.invoices (
  id uuid primary key default gen_random_uuid(),
  location_id uuid not null references public.locations(id) on delete cascade,
  guardian_id uuid not null references public.guardians(id) on delete cascade,
  child_id uuid references public.children(id) on delete set null,
  invoice_number text not null unique,
  description text not null,
  amount numeric(10,2) not null check (amount >= 0),
  status public.invoice_status not null default 'due',
  issued_on date not null,
  due_on date not null,
  paid_at timestamptz,
  created_at timestamptz not null default now()
);

create table public.payments (
  id uuid primary key default gen_random_uuid(),
  invoice_id uuid not null references public.invoices(id) on delete cascade,
  amount numeric(10,2) not null check (amount > 0),
  method_label text not null,
  reference text,
  paid_at timestamptz not null default now()
);

create table public.payment_methods (
  id uuid primary key default gen_random_uuid(),
  guardian_id uuid not null references public.guardians(id) on delete cascade,
  brand text not null,
  last_four text not null check (length(last_four) = 4),
  expires_month integer check (expires_month between 1 and 12),
  expires_year integer,
  is_default boolean not null default true
);

create table public.payroll_records (
  id uuid primary key default gen_random_uuid(),
  staff_id uuid not null references public.staff_members(id) on delete cascade,
  period_start date not null,
  period_end date not null,
  regular_hours numeric(8,2) not null default 0,
  overtime_hours numeric(8,2) not null default 0,
  gross_pay numeric(10,2) not null default 0,
  deductions numeric(10,2) not null default 0,
  net_pay numeric(10,2) generated always as (gross_pay - deductions) stored,
  status text not null default 'draft' check (status in ('draft', 'approved', 'paid')),
  paid_at timestamptz,
  unique (staff_id, period_start, period_end)
);

create table public.staff_schedules (
  id uuid primary key default gen_random_uuid(),
  staff_id uuid not null references public.staff_members(id) on delete cascade,
  weekday integer not null check (weekday between 0 and 6),
  start_time time not null,
  end_time time not null,
  unique (staff_id, weekday)
);

create index on public.children(classroom_id);
create index on public.attendance(child_id, attendance_date desc);
create index on public.daily_logs(child_id, occurred_at desc);
create index on public.messages(thread_id, created_at);
create index on public.notifications(profile_id, created_at desc);
create index on public.staff_shifts(staff_id, clocked_in_at desc);

create or replace function public.touch_updated_at() returns trigger language plpgsql as $$
begin new.updated_at = now(); return new; end $$;
create trigger profiles_touch before update on public.profiles for each row execute function public.touch_updated_at();

create or replace function public.handle_new_user() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (id, first_name, last_name, auth_email)
  values (new.id, coalesce(new.raw_user_meta_data->>'first_name',''), coalesce(new.raw_user_meta_data->>'last_name',''), new.email)
  on conflict (id) do nothing;
  return new;
end $$;
create trigger on_auth_user_created after insert on auth.users for each row execute function public.handle_new_user();

create or replace function public.my_role() returns public.app_role
language sql stable security definer set search_path = public as
$$ select role from public.profiles where id = auth.uid() $$;

create or replace function public.my_location() returns uuid
language sql stable security definer set search_path = public as
$$ select location_id from public.profiles where id = auth.uid() $$;

create or replace function public.my_staff_id() returns uuid
language sql stable security definer set search_path = public as
$$ select id from public.staff_members where profile_id = auth.uid() $$;

create or replace function public.can_access_child(target_child uuid) returns boolean
language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from public.children c
    where c.id = target_child and c.location_id = public.my_location() and (
      public.my_role() in ('manager','admin')
      or (public.my_role() = 'parent' and exists (
        select 1 from public.guardian_children gc join public.guardians g on g.id = gc.guardian_id
        where gc.child_id = c.id and g.profile_id = auth.uid()
      ))
      or (public.my_role() = 'staff' and exists (
        select 1 from public.staff_classrooms sc
        where sc.staff_id = public.my_staff_id() and sc.classroom_id = c.classroom_id
      ))
    )
  )
$$;

create or replace function public.is_thread_participant(target_thread uuid) returns boolean
language sql stable security definer set search_path = public as
$$ select exists(select 1 from public.thread_participants where thread_id = target_thread and profile_id = auth.uid()) $$;

create or replace function public.notify_incident_guardians() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  insert into public.notifications (profile_id, kind, title, body, link)
  select g.profile_id, 'incident', 'Incident report filed',
    'A care team member filed an incident report for ' || c.first_name || '. Please review it.', '/dashboard?view=reports'
  from public.guardian_children gc
  join public.guardians g on g.id = gc.guardian_id
  join public.children c on c.id = gc.child_id
  where gc.child_id = new.child_id;
  return new;
end $$;
create trigger incident_parent_notification after insert on public.incident_reports
for each row execute function public.notify_incident_guardians();

alter table public.locations enable row level security;
alter table public.profiles enable row level security;
alter table public.classrooms enable row level security;
alter table public.guardians enable row level security;
alter table public.staff_members enable row level security;
alter table public.staff_classrooms enable row level security;
alter table public.children enable row level security;
alter table public.guardian_children enable row level security;
alter table public.attendance enable row level security;
alter table public.staff_shifts enable row level security;
alter table public.daily_logs enable row level security;
alter table public.photo_posts enable row level security;
alter table public.announcements enable row level security;
alter table public.incident_reports enable row level security;
alter table public.notifications enable row level security;
alter table public.message_threads enable row level security;
alter table public.thread_participants enable row level security;
alter table public.messages enable row level security;
alter table public.invoices enable row level security;
alter table public.payments enable row level security;
alter table public.payment_methods enable row level security;
alter table public.payroll_records enable row level security;
alter table public.staff_schedules enable row level security;

create policy "location members read location" on public.locations for select using (id = public.my_location());
create policy "profiles visible at location" on public.profiles for select using (id = auth.uid() or (location_id = public.my_location() and role in ('staff','manager','admin')) or public.my_role() in ('manager','admin'));
create policy "users update own basic profile" on public.profiles for update using (id = auth.uid()) with check (id = auth.uid());
create policy "admin manages profiles" on public.profiles for all using (public.my_role() = 'admin' and location_id = public.my_location()) with check (public.my_role() = 'admin' and location_id = public.my_location());

create policy "members read classrooms" on public.classrooms for select using (location_id = public.my_location());
create policy "management manages classrooms" on public.classrooms for all using (public.my_role() in ('manager','admin') and location_id = public.my_location()) with check (public.my_role() in ('manager','admin') and location_id = public.my_location());

create policy "guardians read self or management" on public.guardians for select using (profile_id = auth.uid() or (public.my_role() in ('manager','admin') and location_id = public.my_location()));
create policy "management manages guardians" on public.guardians for all using (public.my_role() in ('manager','admin') and location_id = public.my_location()) with check (public.my_role() in ('manager','admin') and location_id = public.my_location());
create policy "staff visible at location" on public.staff_members for select using (location_id = public.my_location());
create policy "admin manages staff" on public.staff_members for all using (public.my_role() = 'admin' and location_id = public.my_location()) with check (public.my_role() = 'admin' and location_id = public.my_location());
create policy "staff classroom assignments readable" on public.staff_classrooms for select using (exists(select 1 from public.staff_members s where s.id = staff_id and s.location_id = public.my_location()));
create policy "admin manages assignments" on public.staff_classrooms for all using (public.my_role() = 'admin') with check (public.my_role() = 'admin');

create policy "scoped child access" on public.children for select using (public.can_access_child(id));
create policy "management manages children" on public.children for all using (public.my_role() in ('manager','admin') and location_id = public.my_location()) with check (public.my_role() in ('manager','admin') and location_id = public.my_location());
create policy "parents update linked child profile" on public.children for update using (public.my_role() = 'parent' and public.can_access_child(id)) with check (public.my_role() = 'parent' and public.can_access_child(id));
create policy "guardian links visible when child visible" on public.guardian_children for select using (public.can_access_child(child_id));
create policy "management manages guardian links" on public.guardian_children for all using (public.my_role() in ('manager','admin')) with check (public.my_role() in ('manager','admin'));

create policy "scoped attendance read" on public.attendance for select using (public.can_access_child(child_id));
create policy "scoped attendance write" on public.attendance for insert with check (public.can_access_child(child_id));
create policy "scoped attendance update" on public.attendance for update using (public.can_access_child(child_id)) with check (public.can_access_child(child_id));
create policy "scoped logs read" on public.daily_logs for select using (public.can_access_child(child_id));
create policy "educators write logs" on public.daily_logs for insert with check (public.my_role() in ('staff','manager','admin') and public.can_access_child(child_id) and author_id = auth.uid());
create policy "authors or management update logs" on public.daily_logs for update using (author_id = auth.uid() or public.my_role() in ('manager','admin'));
create policy "scoped photos read" on public.photo_posts for select using (public.can_access_child(child_id));
create policy "educators post photos" on public.photo_posts for insert with check (public.my_role() in ('staff','manager','admin') and public.can_access_child(child_id));
create policy "families post linked child photos" on public.photo_posts for insert with check (public.my_role() = 'parent' and public.can_access_child(child_id));

create policy "staff read own or management shifts" on public.staff_shifts for select using (staff_id = public.my_staff_id() or public.my_role() in ('manager','admin'));
create policy "staff clock own shift" on public.staff_shifts for insert with check (staff_id = public.my_staff_id() or public.my_role() in ('manager','admin'));
create policy "staff close own shift" on public.staff_shifts for update using (staff_id = public.my_staff_id() or public.my_role() in ('manager','admin'));

create policy "audience announcements read" on public.announcements for select using (
  location_id = public.my_location() and (
    audience = 'everyone' or (audience = 'parents' and public.my_role() = 'parent') or (audience = 'staff' and public.my_role() in ('staff','manager','admin'))
  )
);
create policy "management publishes announcements" on public.announcements for insert with check (public.my_role() in ('manager','admin') and location_id = public.my_location() and author_id = auth.uid());
create policy "management updates announcements" on public.announcements for update using (public.my_role() in ('manager','admin') and location_id = public.my_location());
create policy "management deletes announcements" on public.announcements for delete using (public.my_role() in ('manager','admin') and location_id = public.my_location());

create policy "scoped incidents read" on public.incident_reports for select using (public.can_access_child(child_id));
create policy "educators file incidents" on public.incident_reports for insert with check (public.my_role() in ('staff','manager','admin') and public.can_access_child(child_id) and reporter_id = auth.uid());
create policy "users read notifications" on public.notifications for select using (profile_id = auth.uid());
create policy "users mark notifications" on public.notifications for update using (profile_id = auth.uid()) with check (profile_id = auth.uid());

create policy "participants read threads" on public.message_threads for select using (public.is_thread_participant(id));
create policy "members create threads" on public.message_threads for insert with check (location_id = public.my_location() and created_by = auth.uid());
create policy "participants read memberships" on public.thread_participants for select using (public.is_thread_participant(thread_id));
create policy "thread creators add participants" on public.thread_participants for insert with check (exists(select 1 from public.message_threads t where t.id = thread_id and t.created_by = auth.uid()));
create policy "participants update read time" on public.thread_participants for update using (profile_id = auth.uid());
create policy "participants read messages" on public.messages for select using (public.is_thread_participant(thread_id));
create policy "participants send messages" on public.messages for insert with check (public.is_thread_participant(thread_id) and sender_id = auth.uid());

create policy "family invoices read" on public.invoices for select using (
  (exists(select 1 from public.guardians g where g.id = guardian_id and g.profile_id = auth.uid()))
  or (public.my_role() in ('manager','admin') and location_id = public.my_location())
);
create policy "management manages invoices" on public.invoices for all using (public.my_role() in ('manager','admin') and location_id = public.my_location()) with check (public.my_role() in ('manager','admin') and location_id = public.my_location());
create policy "family payments read" on public.payments for select using (exists(select 1 from public.invoices i join public.guardians g on g.id = i.guardian_id where i.id = invoice_id and (g.profile_id = auth.uid() or public.my_role() in ('manager','admin'))));
create policy "management records payments" on public.payments for insert with check (public.my_role() in ('manager','admin'));
create policy "family methods read" on public.payment_methods for select using (exists(select 1 from public.guardians g where g.id = guardian_id and (g.profile_id = auth.uid() or public.my_role() in ('manager','admin'))));
create policy "family manages methods" on public.payment_methods for all using (exists(select 1 from public.guardians g where g.id = guardian_id and g.profile_id = auth.uid())) with check (exists(select 1 from public.guardians g where g.id = guardian_id and g.profile_id = auth.uid()));

create policy "staff own payroll admin all" on public.payroll_records for select using (staff_id = public.my_staff_id() or public.my_role() = 'admin');
create policy "admin manages payroll" on public.payroll_records for all using (public.my_role() = 'admin') with check (public.my_role() = 'admin');
create policy "schedules visible at location" on public.staff_schedules for select using (exists(select 1 from public.staff_members s where s.id = staff_id and s.location_id = public.my_location()));
create policy "admin manages schedules" on public.staff_schedules for all using (public.my_role() = 'admin') with check (public.my_role() = 'admin');

insert into storage.buckets (id, name, public) values ('avatars', 'avatars', false), ('child-photos', 'child-photos', false)
on conflict (id) do nothing;
create policy "authenticated avatar reads" on storage.objects for select to authenticated using (bucket_id = 'avatars');
create policy "users upload own avatar" on storage.objects for insert to authenticated with check (bucket_id = 'avatars' and (storage.foldername(name))[1] = auth.uid()::text);
create policy "users update own avatar" on storage.objects for update to authenticated using (bucket_id = 'avatars' and (storage.foldername(name))[1] = auth.uid()::text);
create policy "scoped child photo reads" on storage.objects for select to authenticated using (bucket_id = 'child-photos' and public.can_access_child(((storage.foldername(name))[1])::uuid));
create policy "educators upload child photos" on storage.objects for insert to authenticated with check (bucket_id = 'child-photos' and public.my_role() in ('staff','manager','admin'));
create policy "families upload linked child photos" on storage.objects for insert to authenticated with check (bucket_id = 'child-photos' and public.my_role() = 'parent' and public.can_access_child(((storage.foldername(name))[1])::uuid));

do $$ begin
  alter publication supabase_realtime add table public.attendance;
exception when duplicate_object then null; end $$;
do $$ begin
  alter publication supabase_realtime add table public.messages;
exception when duplicate_object then null; end $$;
do $$ begin
  alter publication supabase_realtime add table public.announcements;
exception when duplicate_object then null; end $$;
do $$ begin
  alter publication supabase_realtime add table public.notifications;
exception when duplicate_object then null; end $$;
