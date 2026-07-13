-- FORGE Daycare live pre-hardening snapshot
-- Captured through authenticated Supabase MCP on 2026-07-13.
-- No application rows or storage objects are included.

-- ENUM public.app_role
create type public.app_role as enum ('parent', 'staff', 'manager', 'admin');

-- ENUM public.attendance_status
create type public.attendance_status as enum ('present', 'completed');

-- ENUM public.audience_type
create type public.audience_type as enum ('everyone', 'parents', 'staff');

-- ENUM public.incident_severity
create type public.incident_severity as enum ('minor', 'moderate', 'serious');

-- ENUM public.invoice_status
create type public.invoice_status as enum ('draft', 'due', 'paid', 'void', 'overdue');

-- TABLE public.announcements
create table public.announcements (
  id uuid default gen_random_uuid() not null,
  location_id uuid not null,
  author_id uuid,
  audience audience_type not null,
  title text not null,
  body text not null,
  pinned boolean default false not null,
  published_at timestamp with time zone default now() not null,
  expires_at timestamp with time zone
);

-- TABLE public.attendance
create table public.attendance (
  id uuid default gen_random_uuid() not null,
  child_id uuid not null,
  attendance_date date default CURRENT_DATE not null,
  checked_in_at timestamp with time zone default now() not null,
  checked_out_at timestamp with time zone,
  checked_in_by uuid,
  checked_out_by uuid,
  status attendance_status default 'present'::attendance_status not null,
  notes text
);

-- TABLE public.children
create table public.children (
  id uuid default gen_random_uuid() not null,
  location_id uuid not null,
  classroom_id uuid,
  first_name text not null,
  last_name text not null,
  preferred_name text,
  birth_date date not null,
  avatar_path text,
  allergies text,
  medical_notes text,
  pickup_notes text,
  enrollment_date date default CURRENT_DATE not null,
  active boolean default true not null,
  created_at timestamp with time zone default now() not null,
  guardian_profile_id uuid
);

-- TABLE public.classrooms
create table public.classrooms (
  id uuid default gen_random_uuid() not null,
  location_id uuid not null,
  name text not null,
  age_group text not null,
  capacity integer not null,
  ratio_children integer default 6 not null,
  color text default '#5B2C8E'::text not null,
  active boolean default true not null
);

-- TABLE public.daily_logs
create table public.daily_logs (
  id uuid default gen_random_uuid() not null,
  child_id uuid not null,
  author_id uuid,
  log_date date default CURRENT_DATE not null,
  activity text,
  mood text,
  meal text,
  nap_minutes integer,
  bathroom text,
  notes text,
  occurred_at timestamp with time zone default now() not null,
  created_at timestamp with time zone default now() not null
);

-- TABLE public.guardian_children
create table public.guardian_children (
  guardian_id uuid not null,
  child_id uuid not null,
  primary_guardian boolean default false not null
);

-- TABLE public.guardians
create table public.guardians (
  id uuid default gen_random_uuid() not null,
  profile_id uuid not null,
  location_id uuid not null,
  relationship_label text default 'Parent'::text,
  emergency_contact boolean default true not null,
  authorized_pickup boolean default true not null
);

-- TABLE public.incident_reports
create table public.incident_reports (
  id uuid default gen_random_uuid() not null,
  child_id uuid not null,
  reporter_id uuid,
  occurred_at timestamp with time zone not null,
  location_detail text not null,
  severity incident_severity not null,
  description text not null,
  action_taken text not null,
  witness_names text,
  parent_notified_at timestamp with time zone default now() not null,
  created_at timestamp with time zone default now() not null
);

-- TABLE public.invoices
create table public.invoices (
  id uuid default gen_random_uuid() not null,
  location_id uuid not null,
  guardian_id uuid not null,
  child_id uuid,
  invoice_number text not null,
  description text not null,
  amount numeric(10,2) not null,
  status invoice_status default 'due'::invoice_status not null,
  issued_on date not null,
  due_on date not null,
  paid_at timestamp with time zone,
  created_at timestamp with time zone default now() not null,
  payments jsonb default '[]'::jsonb not null
);

-- TABLE public.locations
create table public.locations (
  id uuid default gen_random_uuid() not null,
  name text not null,
  address text,
  timezone text default 'America/New_York'::text not null,
  created_at timestamp with time zone default now() not null
);

-- TABLE public.message_threads
create table public.message_threads (
  id uuid default gen_random_uuid() not null,
  location_id uuid not null,
  title text,
  kind text default 'direct'::text not null,
  created_by uuid,
  created_at timestamp with time zone default now() not null
);

-- TABLE public.messages
create table public.messages (
  id uuid default gen_random_uuid() not null,
  thread_id uuid not null,
  sender_id uuid,
  body text default ''::text not null,
  reactions jsonb default '[]'::jsonb not null,
  attachment_path text,
  created_at timestamp with time zone default now() not null
);

-- TABLE public.notifications
create table public.notifications (
  id uuid default gen_random_uuid() not null,
  profile_id uuid not null,
  kind text not null,
  title text not null,
  body text not null,
  link text,
  read_at timestamp with time zone,
  created_at timestamp with time zone default now() not null
);

-- TABLE public.payment_methods
create table public.payment_methods (
  id uuid default gen_random_uuid() not null,
  guardian_id uuid not null,
  brand text not null,
  last_four text not null,
  expires_month integer,
  expires_year integer,
  is_default boolean default true not null
);

-- TABLE public.payments
create table public.payments (
  id uuid default gen_random_uuid() not null,
  invoice_id uuid not null,
  amount numeric(10,2) not null,
  method_label text not null,
  reference text,
  paid_at timestamp with time zone default now() not null
);

-- TABLE public.payroll_records
create table public.payroll_records (
  id uuid default gen_random_uuid() not null,
  staff_id uuid not null,
  period_start date not null,
  period_end date not null,
  regular_hours numeric(8,2) default 0 not null,
  overtime_hours numeric(8,2) default 0 not null,
  gross_pay numeric(10,2) default 0 not null,
  deductions numeric(10,2) default 0 not null,
  net_pay numeric(10,2) generated always as ((gross_pay - deductions)) stored,
  status text default 'draft'::text not null,
  paid_at timestamp with time zone
);

-- TABLE public.photo_posts
create table public.photo_posts (
  id uuid default gen_random_uuid() not null,
  child_id uuid not null,
  uploaded_by uuid,
  storage_path text not null,
  caption text,
  taken_at timestamp with time zone default now() not null,
  created_at timestamp with time zone default now() not null
);

-- TABLE public.profiles
create table public.profiles (
  id uuid not null,
  location_id uuid,
  role app_role default 'parent'::app_role not null,
  first_name text default ''::text not null,
  last_name text default ''::text not null,
  display_name text generated always as (TRIM(BOTH FROM ((first_name || ' '::text) || last_name))) stored,
  avatar_path text,
  login_id text,
  auth_email text,
  phone text,
  active boolean default true not null,
  permissions jsonb default '{}'::jsonb not null,
  created_at timestamp with time zone default now() not null,
  updated_at timestamp with time zone default now() not null
);

-- TABLE public.staff_classrooms
create table public.staff_classrooms (
  staff_id uuid not null,
  classroom_id uuid not null
);

-- TABLE public.staff_members
create table public.staff_members (
  id uuid default gen_random_uuid() not null,
  profile_id uuid not null,
  location_id uuid not null,
  job_title text not null,
  hourly_rate numeric(10,2),
  hire_date date,
  certifications jsonb default '[]'::jsonb not null,
  color text default '#EDE4F5'::text not null
);

-- TABLE public.staff_schedules
create table public.staff_schedules (
  id uuid default gen_random_uuid() not null,
  staff_id uuid not null,
  weekday integer not null,
  start_time time without time zone not null,
  end_time time without time zone not null
);

-- TABLE public.staff_shifts
create table public.staff_shifts (
  id uuid default gen_random_uuid() not null,
  staff_id uuid not null,
  clocked_in_at timestamp with time zone default now() not null,
  clocked_out_at timestamp with time zone,
  notes text,
  created_at timestamp with time zone default now() not null
);

-- TABLE public.thread_participants
create table public.thread_participants (
  thread_id uuid not null,
  profile_id uuid not null,
  last_read_at timestamp with time zone
);

-- CONSTRAINT announcements_author_id_fkey
ALTER TABLE announcements ADD CONSTRAINT announcements_author_id_fkey FOREIGN KEY (author_id) REFERENCES profiles(id) ON DELETE SET NULL;

-- CONSTRAINT announcements_location_id_fkey
ALTER TABLE announcements ADD CONSTRAINT announcements_location_id_fkey FOREIGN KEY (location_id) REFERENCES locations(id) ON DELETE CASCADE;

-- CONSTRAINT announcements_pkey
ALTER TABLE announcements ADD CONSTRAINT announcements_pkey PRIMARY KEY (id);

-- CONSTRAINT attendance_checked_in_by_fkey
ALTER TABLE attendance ADD CONSTRAINT attendance_checked_in_by_fkey FOREIGN KEY (checked_in_by) REFERENCES profiles(id) ON DELETE SET NULL;

-- CONSTRAINT attendance_checked_out_by_fkey
ALTER TABLE attendance ADD CONSTRAINT attendance_checked_out_by_fkey FOREIGN KEY (checked_out_by) REFERENCES profiles(id) ON DELETE SET NULL;

-- CONSTRAINT attendance_child_id_attendance_date_key
ALTER TABLE attendance ADD CONSTRAINT attendance_child_id_attendance_date_key UNIQUE (child_id, attendance_date);

-- CONSTRAINT attendance_child_id_fkey
ALTER TABLE attendance ADD CONSTRAINT attendance_child_id_fkey FOREIGN KEY (child_id) REFERENCES children(id) ON DELETE CASCADE;

-- CONSTRAINT attendance_pkey
ALTER TABLE attendance ADD CONSTRAINT attendance_pkey PRIMARY KEY (id);

-- CONSTRAINT children_classroom_id_fkey
ALTER TABLE children ADD CONSTRAINT children_classroom_id_fkey FOREIGN KEY (classroom_id) REFERENCES classrooms(id) ON DELETE SET NULL;

-- CONSTRAINT children_guardian_profile_id_fkey
ALTER TABLE children ADD CONSTRAINT children_guardian_profile_id_fkey FOREIGN KEY (guardian_profile_id) REFERENCES profiles(id) ON DELETE SET NULL;

-- CONSTRAINT children_location_id_fkey
ALTER TABLE children ADD CONSTRAINT children_location_id_fkey FOREIGN KEY (location_id) REFERENCES locations(id) ON DELETE CASCADE;

-- CONSTRAINT children_pkey
ALTER TABLE children ADD CONSTRAINT children_pkey PRIMARY KEY (id);

-- CONSTRAINT classrooms_capacity_check
ALTER TABLE classrooms ADD CONSTRAINT classrooms_capacity_check CHECK (capacity > 0);

-- CONSTRAINT classrooms_location_id_fkey
ALTER TABLE classrooms ADD CONSTRAINT classrooms_location_id_fkey FOREIGN KEY (location_id) REFERENCES locations(id) ON DELETE CASCADE;

-- CONSTRAINT classrooms_location_id_name_key
ALTER TABLE classrooms ADD CONSTRAINT classrooms_location_id_name_key UNIQUE (location_id, name);

-- CONSTRAINT classrooms_pkey
ALTER TABLE classrooms ADD CONSTRAINT classrooms_pkey PRIMARY KEY (id);

-- CONSTRAINT classrooms_ratio_children_check
ALTER TABLE classrooms ADD CONSTRAINT classrooms_ratio_children_check CHECK (ratio_children > 0);

-- CONSTRAINT daily_logs_author_id_fkey
ALTER TABLE daily_logs ADD CONSTRAINT daily_logs_author_id_fkey FOREIGN KEY (author_id) REFERENCES profiles(id) ON DELETE SET NULL;

-- CONSTRAINT daily_logs_child_id_fkey
ALTER TABLE daily_logs ADD CONSTRAINT daily_logs_child_id_fkey FOREIGN KEY (child_id) REFERENCES children(id) ON DELETE CASCADE;

-- CONSTRAINT daily_logs_pkey
ALTER TABLE daily_logs ADD CONSTRAINT daily_logs_pkey PRIMARY KEY (id);

-- CONSTRAINT guardian_children_child_id_fkey
ALTER TABLE guardian_children ADD CONSTRAINT guardian_children_child_id_fkey FOREIGN KEY (child_id) REFERENCES children(id) ON DELETE CASCADE;

-- CONSTRAINT guardian_children_guardian_id_fkey
ALTER TABLE guardian_children ADD CONSTRAINT guardian_children_guardian_id_fkey FOREIGN KEY (guardian_id) REFERENCES guardians(id) ON DELETE CASCADE;

-- CONSTRAINT guardian_children_pkey
ALTER TABLE guardian_children ADD CONSTRAINT guardian_children_pkey PRIMARY KEY (guardian_id, child_id);

-- CONSTRAINT guardians_location_id_fkey
ALTER TABLE guardians ADD CONSTRAINT guardians_location_id_fkey FOREIGN KEY (location_id) REFERENCES locations(id) ON DELETE CASCADE;

-- CONSTRAINT guardians_pkey
ALTER TABLE guardians ADD CONSTRAINT guardians_pkey PRIMARY KEY (id);

-- CONSTRAINT guardians_profile_id_fkey
ALTER TABLE guardians ADD CONSTRAINT guardians_profile_id_fkey FOREIGN KEY (profile_id) REFERENCES profiles(id) ON DELETE CASCADE;

-- CONSTRAINT guardians_profile_id_key
ALTER TABLE guardians ADD CONSTRAINT guardians_profile_id_key UNIQUE (profile_id);

-- CONSTRAINT incident_reports_child_id_fkey
ALTER TABLE incident_reports ADD CONSTRAINT incident_reports_child_id_fkey FOREIGN KEY (child_id) REFERENCES children(id) ON DELETE CASCADE;

-- CONSTRAINT incident_reports_pkey
ALTER TABLE incident_reports ADD CONSTRAINT incident_reports_pkey PRIMARY KEY (id);

-- CONSTRAINT incident_reports_reporter_id_fkey
ALTER TABLE incident_reports ADD CONSTRAINT incident_reports_reporter_id_fkey FOREIGN KEY (reporter_id) REFERENCES profiles(id) ON DELETE SET NULL;

-- CONSTRAINT invoices_amount_check
ALTER TABLE invoices ADD CONSTRAINT invoices_amount_check CHECK (amount >= 0::numeric);

-- CONSTRAINT invoices_child_id_fkey
ALTER TABLE invoices ADD CONSTRAINT invoices_child_id_fkey FOREIGN KEY (child_id) REFERENCES children(id) ON DELETE SET NULL;

-- CONSTRAINT invoices_guardian_id_fkey
ALTER TABLE invoices ADD CONSTRAINT invoices_guardian_id_fkey FOREIGN KEY (guardian_id) REFERENCES profiles(id) ON DELETE CASCADE;

-- CONSTRAINT invoices_invoice_number_key
ALTER TABLE invoices ADD CONSTRAINT invoices_invoice_number_key UNIQUE (invoice_number);

-- CONSTRAINT invoices_location_id_fkey
ALTER TABLE invoices ADD CONSTRAINT invoices_location_id_fkey FOREIGN KEY (location_id) REFERENCES locations(id) ON DELETE CASCADE;

-- CONSTRAINT invoices_pkey
ALTER TABLE invoices ADD CONSTRAINT invoices_pkey PRIMARY KEY (id);

-- CONSTRAINT locations_pkey
ALTER TABLE locations ADD CONSTRAINT locations_pkey PRIMARY KEY (id);

-- CONSTRAINT message_threads_created_by_fkey
ALTER TABLE message_threads ADD CONSTRAINT message_threads_created_by_fkey FOREIGN KEY (created_by) REFERENCES profiles(id) ON DELETE SET NULL;

-- CONSTRAINT message_threads_kind_check
ALTER TABLE message_threads ADD CONSTRAINT message_threads_kind_check CHECK (kind = ANY (ARRAY['direct'::text, 'group'::text, 'broadcast'::text]));

-- CONSTRAINT message_threads_location_id_fkey
ALTER TABLE message_threads ADD CONSTRAINT message_threads_location_id_fkey FOREIGN KEY (location_id) REFERENCES locations(id) ON DELETE CASCADE;

-- CONSTRAINT message_threads_pkey
ALTER TABLE message_threads ADD CONSTRAINT message_threads_pkey PRIMARY KEY (id);

-- CONSTRAINT messages_body_check
ALTER TABLE messages ADD CONSTRAINT messages_body_check CHECK (length(body) <= 4000);

-- CONSTRAINT messages_pkey
ALTER TABLE messages ADD CONSTRAINT messages_pkey PRIMARY KEY (id);

-- CONSTRAINT messages_sender_id_fkey
ALTER TABLE messages ADD CONSTRAINT messages_sender_id_fkey FOREIGN KEY (sender_id) REFERENCES profiles(id) ON DELETE SET NULL;

-- CONSTRAINT messages_thread_id_fkey
ALTER TABLE messages ADD CONSTRAINT messages_thread_id_fkey FOREIGN KEY (thread_id) REFERENCES message_threads(id) ON DELETE CASCADE;

-- CONSTRAINT notifications_pkey
ALTER TABLE notifications ADD CONSTRAINT notifications_pkey PRIMARY KEY (id);

-- CONSTRAINT notifications_profile_id_fkey
ALTER TABLE notifications ADD CONSTRAINT notifications_profile_id_fkey FOREIGN KEY (profile_id) REFERENCES profiles(id) ON DELETE CASCADE;

-- CONSTRAINT payment_methods_expires_month_check
ALTER TABLE payment_methods ADD CONSTRAINT payment_methods_expires_month_check CHECK (expires_month >= 1 AND expires_month <= 12);

-- CONSTRAINT payment_methods_guardian_id_fkey
ALTER TABLE payment_methods ADD CONSTRAINT payment_methods_guardian_id_fkey FOREIGN KEY (guardian_id) REFERENCES profiles(id) ON DELETE CASCADE;

-- CONSTRAINT payment_methods_last_four_check
ALTER TABLE payment_methods ADD CONSTRAINT payment_methods_last_four_check CHECK (length(last_four) = 4);

-- CONSTRAINT payment_methods_pkey
ALTER TABLE payment_methods ADD CONSTRAINT payment_methods_pkey PRIMARY KEY (id);

-- CONSTRAINT payments_amount_check
ALTER TABLE payments ADD CONSTRAINT payments_amount_check CHECK (amount > 0::numeric);

-- CONSTRAINT payments_invoice_id_fkey
ALTER TABLE payments ADD CONSTRAINT payments_invoice_id_fkey FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE CASCADE;

-- CONSTRAINT payments_pkey
ALTER TABLE payments ADD CONSTRAINT payments_pkey PRIMARY KEY (id);

-- CONSTRAINT payroll_records_pkey
ALTER TABLE payroll_records ADD CONSTRAINT payroll_records_pkey PRIMARY KEY (id);

-- CONSTRAINT payroll_records_staff_id_fkey
ALTER TABLE payroll_records ADD CONSTRAINT payroll_records_staff_id_fkey FOREIGN KEY (staff_id) REFERENCES staff_members(id) ON DELETE CASCADE;

-- CONSTRAINT payroll_records_staff_id_period_start_period_end_key
ALTER TABLE payroll_records ADD CONSTRAINT payroll_records_staff_id_period_start_period_end_key UNIQUE (staff_id, period_start, period_end);

-- CONSTRAINT payroll_records_status_check
ALTER TABLE payroll_records ADD CONSTRAINT payroll_records_status_check CHECK (status = ANY (ARRAY['draft'::text, 'approved'::text, 'paid'::text]));

-- CONSTRAINT photo_posts_child_id_fkey
ALTER TABLE photo_posts ADD CONSTRAINT photo_posts_child_id_fkey FOREIGN KEY (child_id) REFERENCES children(id) ON DELETE CASCADE;

-- CONSTRAINT photo_posts_pkey
ALTER TABLE photo_posts ADD CONSTRAINT photo_posts_pkey PRIMARY KEY (id);

-- CONSTRAINT photo_posts_uploaded_by_fkey
ALTER TABLE photo_posts ADD CONSTRAINT photo_posts_uploaded_by_fkey FOREIGN KEY (uploaded_by) REFERENCES profiles(id) ON DELETE SET NULL;

-- CONSTRAINT profiles_auth_email_key
ALTER TABLE profiles ADD CONSTRAINT profiles_auth_email_key UNIQUE (auth_email);

-- CONSTRAINT profiles_id_fkey
ALTER TABLE profiles ADD CONSTRAINT profiles_id_fkey FOREIGN KEY (id) REFERENCES auth.users(id) ON DELETE CASCADE;

-- CONSTRAINT profiles_location_id_fkey
ALTER TABLE profiles ADD CONSTRAINT profiles_location_id_fkey FOREIGN KEY (location_id) REFERENCES locations(id) ON DELETE SET NULL;

-- CONSTRAINT profiles_login_id_key
ALTER TABLE profiles ADD CONSTRAINT profiles_login_id_key UNIQUE (login_id);

-- CONSTRAINT profiles_pkey
ALTER TABLE profiles ADD CONSTRAINT profiles_pkey PRIMARY KEY (id);

-- CONSTRAINT staff_classrooms_classroom_id_fkey
ALTER TABLE staff_classrooms ADD CONSTRAINT staff_classrooms_classroom_id_fkey FOREIGN KEY (classroom_id) REFERENCES classrooms(id) ON DELETE CASCADE;

-- CONSTRAINT staff_classrooms_pkey
ALTER TABLE staff_classrooms ADD CONSTRAINT staff_classrooms_pkey PRIMARY KEY (staff_id, classroom_id);

-- CONSTRAINT staff_classrooms_staff_id_fkey
ALTER TABLE staff_classrooms ADD CONSTRAINT staff_classrooms_staff_id_fkey FOREIGN KEY (staff_id) REFERENCES staff_members(id) ON DELETE CASCADE;

-- CONSTRAINT staff_members_location_id_fkey
ALTER TABLE staff_members ADD CONSTRAINT staff_members_location_id_fkey FOREIGN KEY (location_id) REFERENCES locations(id) ON DELETE CASCADE;

-- CONSTRAINT staff_members_pkey
ALTER TABLE staff_members ADD CONSTRAINT staff_members_pkey PRIMARY KEY (id);

-- CONSTRAINT staff_members_profile_id_fkey
ALTER TABLE staff_members ADD CONSTRAINT staff_members_profile_id_fkey FOREIGN KEY (profile_id) REFERENCES profiles(id) ON DELETE CASCADE;

-- CONSTRAINT staff_members_profile_id_key
ALTER TABLE staff_members ADD CONSTRAINT staff_members_profile_id_key UNIQUE (profile_id);

-- CONSTRAINT staff_schedules_pkey
ALTER TABLE staff_schedules ADD CONSTRAINT staff_schedules_pkey PRIMARY KEY (id);

-- CONSTRAINT staff_schedules_staff_id_fkey
ALTER TABLE staff_schedules ADD CONSTRAINT staff_schedules_staff_id_fkey FOREIGN KEY (staff_id) REFERENCES staff_members(id) ON DELETE CASCADE;

-- CONSTRAINT staff_schedules_staff_id_weekday_key
ALTER TABLE staff_schedules ADD CONSTRAINT staff_schedules_staff_id_weekday_key UNIQUE (staff_id, weekday);

-- CONSTRAINT staff_schedules_weekday_check
ALTER TABLE staff_schedules ADD CONSTRAINT staff_schedules_weekday_check CHECK (weekday >= 0 AND weekday <= 6);

-- CONSTRAINT staff_shifts_pkey
ALTER TABLE staff_shifts ADD CONSTRAINT staff_shifts_pkey PRIMARY KEY (id);

-- CONSTRAINT staff_shifts_staff_id_fkey
ALTER TABLE staff_shifts ADD CONSTRAINT staff_shifts_staff_id_fkey FOREIGN KEY (staff_id) REFERENCES staff_members(id) ON DELETE CASCADE;

-- CONSTRAINT thread_participants_pkey
ALTER TABLE thread_participants ADD CONSTRAINT thread_participants_pkey PRIMARY KEY (thread_id, profile_id);

-- CONSTRAINT thread_participants_profile_id_fkey
ALTER TABLE thread_participants ADD CONSTRAINT thread_participants_profile_id_fkey FOREIGN KEY (profile_id) REFERENCES profiles(id) ON DELETE CASCADE;

-- CONSTRAINT thread_participants_thread_id_fkey
ALTER TABLE thread_participants ADD CONSTRAINT thread_participants_thread_id_fkey FOREIGN KEY (thread_id) REFERENCES message_threads(id) ON DELETE CASCADE;

-- INDEX attendance_child_id_attendance_date_idx
CREATE INDEX attendance_child_id_attendance_date_idx ON public.attendance USING btree (child_id, attendance_date DESC);

-- INDEX children_classroom_id_idx
CREATE INDEX children_classroom_id_idx ON public.children USING btree (classroom_id);

-- INDEX daily_logs_child_id_occurred_at_idx
CREATE INDEX daily_logs_child_id_occurred_at_idx ON public.daily_logs USING btree (child_id, occurred_at DESC);

-- INDEX messages_thread_id_created_at_idx
CREATE INDEX messages_thread_id_created_at_idx ON public.messages USING btree (thread_id, created_at);

-- INDEX notifications_profile_id_created_at_idx
CREATE INDEX notifications_profile_id_created_at_idx ON public.notifications USING btree (profile_id, created_at DESC);

-- INDEX staff_shifts_staff_id_clocked_in_at_idx
CREATE INDEX staff_shifts_staff_id_clocked_in_at_idx ON public.staff_shifts USING btree (staff_id, clocked_in_at DESC);

CREATE OR REPLACE FUNCTION public.touch_updated_at()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO 'public'
AS $function$
begin new.updated_at = now(); return new; end $function$


CREATE OR REPLACE FUNCTION public.handle_new_user()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
begin
  insert into public.profiles (id, first_name, last_name, auth_email)
  values (new.id, coalesce(new.raw_user_meta_data->>'first_name',''), coalesce(new.raw_user_meta_data->>'last_name',''), new.email)
  on conflict (id) do nothing;
  return new;
end $function$


CREATE OR REPLACE FUNCTION public.my_role()
 RETURNS app_role
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'public'
AS $function$ select role from public.profiles where id = auth.uid() $function$


CREATE OR REPLACE FUNCTION public.my_location()
 RETURNS uuid
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'public'
AS $function$ select location_id from public.profiles where id = auth.uid() $function$


CREATE OR REPLACE FUNCTION public.my_staff_id()
 RETURNS uuid
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'public'
AS $function$ select id from public.staff_members where profile_id = auth.uid() $function$


CREATE OR REPLACE FUNCTION public.can_access_child(target_child uuid)
 RETURNS boolean
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
  select exists (
    select 1 from public.children c
    where c.id = target_child and c.location_id = public.my_location() and (
      public.my_role() in ('manager','admin')
      or (public.my_role() = 'parent' and (
        c.guardian_profile_id = auth.uid()
        or exists (
          select 1 from public.guardian_children gc join public.guardians g on g.id = gc.guardian_id
          where gc.child_id = c.id and g.profile_id = auth.uid()
        )
      ))
      or (public.my_role() = 'staff' and exists (
        select 1 from public.staff_classrooms sc
        where sc.staff_id = public.my_staff_id() and sc.classroom_id = c.classroom_id
      ))
    )
  )
$function$


CREATE OR REPLACE FUNCTION public.is_thread_participant(target_thread uuid)
 RETURNS boolean
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'public'
AS $function$ select exists(select 1 from public.thread_participants where thread_id = target_thread and profile_id = auth.uid()) $function$


CREATE OR REPLACE FUNCTION public.notify_incident_guardians()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
begin
  insert into public.notifications (profile_id, kind, title, body, link)
  select c.guardian_profile_id, 'incident', 'Incident report for ' || c.first_name,
    'A care team member submitted an incident report. Please review it with the center.', null
  from public.children c
  where c.id = new.child_id and c.guardian_profile_id is not null;
  return new;
end $function$


CREATE OR REPLACE FUNCTION public.notify_announcement_audience()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
begin
  insert into public.notifications (profile_id, kind, title, body, link)
  select p.id, 'announcement', new.title,
    case when length(new.body) > 90 then left(new.body, 90) || '…' else new.body end, '/dashboard'
  from public.profiles p
  where p.location_id = new.location_id and p.active and p.id <> coalesce(new.author_id, '00000000-0000-0000-0000-000000000000'::uuid)
    and (new.audience = 'everyone' or (new.audience = 'parents' and p.role = 'parent') or (new.audience = 'staff' and p.role = 'staff'));
  return new;
end $function$


CREATE OR REPLACE FUNCTION public.guard_invoice_update()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
begin
  if public.my_role() in ('manager','admin') then return new; end if;
  new.amount := old.amount;
  new.invoice_number := old.invoice_number;
  new.description := old.description;
  new.guardian_id := old.guardian_id;
  new.child_id := old.child_id;
  new.location_id := old.location_id;
  new.issued_on := old.issued_on;
  new.due_on := old.due_on;
  return new;
end $function$


CREATE OR REPLACE FUNCTION public.guard_message_update()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
begin
  new.body := old.body;
  new.sender_id := old.sender_id;
  new.thread_id := old.thread_id;
  new.attachment_path := old.attachment_path;
  new.created_at := old.created_at;
  return new;
end $function$


CREATE OR REPLACE FUNCTION public.guard_child_update()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
begin
  if public.my_role() <> 'parent' then return new; end if;
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
  return new;
end $function$


-- TRIGGER announcement_audience_notification
CREATE TRIGGER announcement_audience_notification AFTER INSERT ON public.announcements FOR EACH ROW EXECUTE FUNCTION notify_announcement_audience();

-- TRIGGER child_update_guard
CREATE TRIGGER child_update_guard BEFORE UPDATE ON public.children FOR EACH ROW EXECUTE FUNCTION guard_child_update();

-- TRIGGER incident_parent_notification
CREATE TRIGGER incident_parent_notification AFTER INSERT ON public.incident_reports FOR EACH ROW EXECUTE FUNCTION notify_incident_guardians();

-- TRIGGER invoice_update_guard
CREATE TRIGGER invoice_update_guard BEFORE UPDATE ON public.invoices FOR EACH ROW EXECUTE FUNCTION guard_invoice_update();

-- TRIGGER message_update_guard
CREATE TRIGGER message_update_guard BEFORE UPDATE ON public.messages FOR EACH ROW EXECUTE FUNCTION guard_message_update();

-- TRIGGER profiles_touch
CREATE TRIGGER profiles_touch BEFORE UPDATE ON public.profiles FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

-- POLICY audience announcements read
CREATE POLICY "audience announcements read" ON public.announcements AS PERMISSIVE FOR SELECT TO public USING (((location_id = my_location()) AND ((my_role() = ANY (ARRAY['manager'::app_role, 'admin'::app_role])) OR (audience = 'everyone'::audience_type) OR ((audience = 'parents'::audience_type) AND (my_role() = 'parent'::app_role)) OR ((audience = 'staff'::audience_type) AND (my_role() = 'staff'::app_role)))));

-- POLICY management deletes announcements
CREATE POLICY "management deletes announcements" ON public.announcements AS PERMISSIVE FOR DELETE TO public USING (((my_role() = ANY (ARRAY['manager'::app_role, 'admin'::app_role])) AND (location_id = my_location())));

-- POLICY management publishes announcements
CREATE POLICY "management publishes announcements" ON public.announcements AS PERMISSIVE FOR INSERT TO public WITH CHECK (((my_role() = ANY (ARRAY['manager'::app_role, 'admin'::app_role])) AND (location_id = my_location()) AND (author_id = auth.uid())));

-- POLICY management updates announcements
CREATE POLICY "management updates announcements" ON public.announcements AS PERMISSIVE FOR UPDATE TO public USING (((my_role() = ANY (ARRAY['manager'::app_role, 'admin'::app_role])) AND (location_id = my_location())));

-- POLICY scoped attendance read
CREATE POLICY "scoped attendance read" ON public.attendance AS PERMISSIVE FOR SELECT TO public USING (can_access_child(child_id));

-- POLICY scoped attendance update
CREATE POLICY "scoped attendance update" ON public.attendance AS PERMISSIVE FOR UPDATE TO public USING (can_access_child(child_id)) WITH CHECK (can_access_child(child_id));

-- POLICY scoped attendance write
CREATE POLICY "scoped attendance write" ON public.attendance AS PERMISSIVE FOR INSERT TO public WITH CHECK (can_access_child(child_id));

-- POLICY management manages children
CREATE POLICY "management manages children" ON public.children AS PERMISSIVE FOR ALL TO public USING (((my_role() = ANY (ARRAY['manager'::app_role, 'admin'::app_role])) AND (location_id = my_location()))) WITH CHECK (((my_role() = ANY (ARRAY['manager'::app_role, 'admin'::app_role])) AND (location_id = my_location())));

-- POLICY parents update linked child profile
CREATE POLICY "parents update linked child profile" ON public.children AS PERMISSIVE FOR UPDATE TO public USING (((my_role() = 'parent'::app_role) AND can_access_child(id))) WITH CHECK (((my_role() = 'parent'::app_role) AND can_access_child(id)));

-- POLICY scoped child access
CREATE POLICY "scoped child access" ON public.children AS PERMISSIVE FOR SELECT TO public USING (can_access_child(id));

-- POLICY management manages classrooms
CREATE POLICY "management manages classrooms" ON public.classrooms AS PERMISSIVE FOR ALL TO public USING (((my_role() = ANY (ARRAY['manager'::app_role, 'admin'::app_role])) AND (location_id = my_location()))) WITH CHECK (((my_role() = ANY (ARRAY['manager'::app_role, 'admin'::app_role])) AND (location_id = my_location())));

-- POLICY members read classrooms
CREATE POLICY "members read classrooms" ON public.classrooms AS PERMISSIVE FOR SELECT TO public USING ((location_id = my_location()));

-- POLICY authors or management update logs
CREATE POLICY "authors or management update logs" ON public.daily_logs AS PERMISSIVE FOR UPDATE TO public USING (((author_id = auth.uid()) OR (my_role() = ANY (ARRAY['manager'::app_role, 'admin'::app_role]))));

-- POLICY educators write logs
CREATE POLICY "educators write logs" ON public.daily_logs AS PERMISSIVE FOR INSERT TO public WITH CHECK (((my_role() = ANY (ARRAY['staff'::app_role, 'manager'::app_role, 'admin'::app_role])) AND can_access_child(child_id) AND (author_id = auth.uid())));

-- POLICY scoped logs read
CREATE POLICY "scoped logs read" ON public.daily_logs AS PERMISSIVE FOR SELECT TO public USING (can_access_child(child_id));

-- POLICY guardian links visible when child visible
CREATE POLICY "guardian links visible when child visible" ON public.guardian_children AS PERMISSIVE FOR SELECT TO public USING (can_access_child(child_id));

-- POLICY management manages guardian links
CREATE POLICY "management manages guardian links" ON public.guardian_children AS PERMISSIVE FOR ALL TO public USING ((my_role() = ANY (ARRAY['manager'::app_role, 'admin'::app_role]))) WITH CHECK ((my_role() = ANY (ARRAY['manager'::app_role, 'admin'::app_role])));

-- POLICY guardians read self or management
CREATE POLICY "guardians read self or management" ON public.guardians AS PERMISSIVE FOR SELECT TO public USING (((profile_id = auth.uid()) OR ((my_role() = ANY (ARRAY['manager'::app_role, 'admin'::app_role])) AND (location_id = my_location()))));

-- POLICY management manages guardians
CREATE POLICY "management manages guardians" ON public.guardians AS PERMISSIVE FOR ALL TO public USING (((my_role() = ANY (ARRAY['manager'::app_role, 'admin'::app_role])) AND (location_id = my_location()))) WITH CHECK (((my_role() = ANY (ARRAY['manager'::app_role, 'admin'::app_role])) AND (location_id = my_location())));

-- POLICY educators file incidents
CREATE POLICY "educators file incidents" ON public.incident_reports AS PERMISSIVE FOR INSERT TO public WITH CHECK (((my_role() = ANY (ARRAY['staff'::app_role, 'manager'::app_role, 'admin'::app_role])) AND can_access_child(child_id) AND (reporter_id = auth.uid())));

-- POLICY scoped incidents read
CREATE POLICY "scoped incidents read" ON public.incident_reports AS PERMISSIVE FOR SELECT TO public USING (can_access_child(child_id));

-- POLICY family invoices read
CREATE POLICY "family invoices read" ON public.invoices AS PERMISSIVE FOR SELECT TO public USING (((guardian_id = auth.uid()) OR ((my_role() = ANY (ARRAY['manager'::app_role, 'admin'::app_role])) AND (location_id = my_location()))));

-- POLICY family invoices update paid
CREATE POLICY "family invoices update paid" ON public.invoices AS PERMISSIVE FOR UPDATE TO public USING ((guardian_id = auth.uid())) WITH CHECK ((guardian_id = auth.uid()));

-- POLICY management manages invoices
CREATE POLICY "management manages invoices" ON public.invoices AS PERMISSIVE FOR ALL TO public USING (((my_role() = ANY (ARRAY['manager'::app_role, 'admin'::app_role])) AND (location_id = my_location()))) WITH CHECK (((my_role() = ANY (ARRAY['manager'::app_role, 'admin'::app_role])) AND (location_id = my_location())));

-- POLICY location members read location
CREATE POLICY "location members read location" ON public.locations AS PERMISSIVE FOR SELECT TO public USING ((id = my_location()));

-- POLICY members create threads
CREATE POLICY "members create threads" ON public.message_threads AS PERMISSIVE FOR INSERT TO public WITH CHECK (((location_id = my_location()) AND (created_by = auth.uid())));

-- POLICY participants read threads
CREATE POLICY "participants read threads" ON public.message_threads AS PERMISSIVE FOR SELECT TO public USING ((is_thread_participant(id) OR ((my_role() = ANY (ARRAY['manager'::app_role, 'admin'::app_role])) AND (location_id = my_location()))));

-- POLICY participants update threads
CREATE POLICY "participants update threads" ON public.message_threads AS PERMISSIVE FOR UPDATE TO public USING ((is_thread_participant(id) OR ((my_role() = ANY (ARRAY['manager'::app_role, 'admin'::app_role])) AND (location_id = my_location())))) WITH CHECK ((is_thread_participant(id) OR ((my_role() = ANY (ARRAY['manager'::app_role, 'admin'::app_role])) AND (location_id = my_location()))));

-- POLICY participants react to messages
CREATE POLICY "participants react to messages" ON public.messages AS PERMISSIVE FOR UPDATE TO public USING ((is_thread_participant(thread_id) OR (my_role() = ANY (ARRAY['manager'::app_role, 'admin'::app_role])))) WITH CHECK ((is_thread_participant(thread_id) OR (my_role() = ANY (ARRAY['manager'::app_role, 'admin'::app_role]))));

-- POLICY participants read messages
CREATE POLICY "participants read messages" ON public.messages AS PERMISSIVE FOR SELECT TO public USING ((is_thread_participant(thread_id) OR (my_role() = ANY (ARRAY['manager'::app_role, 'admin'::app_role]))));

-- POLICY participants send messages
CREATE POLICY "participants send messages" ON public.messages AS PERMISSIVE FOR INSERT TO public WITH CHECK (((is_thread_participant(thread_id) OR (my_role() = ANY (ARRAY['manager'::app_role, 'admin'::app_role]))) AND (sender_id = auth.uid())));

-- POLICY members create notifications
CREATE POLICY "members create notifications" ON public.notifications AS PERMISSIVE FOR INSERT TO public WITH CHECK (((auth.uid() IS NOT NULL) AND ((profile_id = auth.uid()) OR (EXISTS ( SELECT 1
   FROM (thread_participants a
     JOIN thread_participants b ON ((a.thread_id = b.thread_id)))
  WHERE ((a.profile_id = auth.uid()) AND (b.profile_id = notifications.profile_id)))) OR ((my_role() = ANY (ARRAY['manager'::app_role, 'admin'::app_role])) AND (EXISTS ( SELECT 1
   FROM profiles p
  WHERE ((p.id = notifications.profile_id) AND (p.location_id = my_location()))))) OR ((my_role() = 'parent'::app_role) AND (EXISTS ( SELECT 1
   FROM profiles p
  WHERE ((p.id = notifications.profile_id) AND (p.role = ANY (ARRAY['manager'::app_role, 'admin'::app_role])) AND (p.location_id = my_location()))))))));

-- POLICY users mark notifications
CREATE POLICY "users mark notifications" ON public.notifications AS PERMISSIVE FOR UPDATE TO public USING ((profile_id = auth.uid())) WITH CHECK ((profile_id = auth.uid()));

-- POLICY users read notifications
CREATE POLICY "users read notifications" ON public.notifications AS PERMISSIVE FOR SELECT TO public USING ((profile_id = auth.uid()));

-- POLICY family manages methods
CREATE POLICY "family manages methods" ON public.payment_methods AS PERMISSIVE FOR ALL TO public USING ((guardian_id = auth.uid())) WITH CHECK ((guardian_id = auth.uid()));

-- POLICY family methods read
CREATE POLICY "family methods read" ON public.payment_methods AS PERMISSIVE FOR SELECT TO public USING (((guardian_id = auth.uid()) OR (my_role() = ANY (ARRAY['manager'::app_role, 'admin'::app_role]))));

-- POLICY family or management record payments
CREATE POLICY "family or management record payments" ON public.payments AS PERMISSIVE FOR INSERT TO public WITH CHECK ((EXISTS ( SELECT 1
   FROM invoices i
  WHERE ((i.id = payments.invoice_id) AND ((i.guardian_id = auth.uid()) OR (my_role() = ANY (ARRAY['manager'::app_role, 'admin'::app_role])))))));

-- POLICY family payments read
CREATE POLICY "family payments read" ON public.payments AS PERMISSIVE FOR SELECT TO public USING ((EXISTS ( SELECT 1
   FROM invoices i
  WHERE ((i.id = payments.invoice_id) AND ((i.guardian_id = auth.uid()) OR (my_role() = ANY (ARRAY['manager'::app_role, 'admin'::app_role])))))));

-- POLICY admin manages payroll
CREATE POLICY "admin manages payroll" ON public.payroll_records AS PERMISSIVE FOR ALL TO public USING ((my_role() = 'admin'::app_role)) WITH CHECK ((my_role() = 'admin'::app_role));

-- POLICY staff own payroll admin all
CREATE POLICY "staff own payroll admin all" ON public.payroll_records AS PERMISSIVE FOR SELECT TO public USING (((staff_id = my_staff_id()) OR (my_role() = 'admin'::app_role)));

-- POLICY educators post photos
CREATE POLICY "educators post photos" ON public.photo_posts AS PERMISSIVE FOR INSERT TO public WITH CHECK (((my_role() = ANY (ARRAY['staff'::app_role, 'manager'::app_role, 'admin'::app_role])) AND can_access_child(child_id)));

-- POLICY families post linked child photos
CREATE POLICY "families post linked child photos" ON public.photo_posts AS PERMISSIVE FOR INSERT TO public WITH CHECK (((my_role() = 'parent'::app_role) AND can_access_child(child_id)));

-- POLICY scoped photos read
CREATE POLICY "scoped photos read" ON public.photo_posts AS PERMISSIVE FOR SELECT TO public USING (can_access_child(child_id));

-- POLICY admin manages profiles
CREATE POLICY "admin manages profiles" ON public.profiles AS PERMISSIVE FOR ALL TO public USING (((my_role() = 'admin'::app_role) AND (location_id = my_location()))) WITH CHECK (((my_role() = 'admin'::app_role) AND (location_id = my_location())));

-- POLICY profiles visible at location
CREATE POLICY "profiles visible at location" ON public.profiles AS PERMISSIVE FOR SELECT TO public USING (((id = auth.uid()) OR (location_id = my_location())));

-- POLICY users update own basic profile
CREATE POLICY "users update own basic profile" ON public.profiles AS PERMISSIVE FOR UPDATE TO public USING ((id = auth.uid())) WITH CHECK ((id = auth.uid()));

-- POLICY admin manages assignments
CREATE POLICY "admin manages assignments" ON public.staff_classrooms AS PERMISSIVE FOR ALL TO public USING ((my_role() = 'admin'::app_role)) WITH CHECK ((my_role() = 'admin'::app_role));

-- POLICY staff classroom assignments readable
CREATE POLICY "staff classroom assignments readable" ON public.staff_classrooms AS PERMISSIVE FOR SELECT TO public USING ((EXISTS ( SELECT 1
   FROM staff_members s
  WHERE ((s.id = staff_classrooms.staff_id) AND (s.location_id = my_location())))));

-- POLICY admin manages staff
CREATE POLICY "admin manages staff" ON public.staff_members AS PERMISSIVE FOR ALL TO public USING (((my_role() = 'admin'::app_role) AND (location_id = my_location()))) WITH CHECK (((my_role() = 'admin'::app_role) AND (location_id = my_location())));

-- POLICY staff visible at location
CREATE POLICY "staff visible at location" ON public.staff_members AS PERMISSIVE FOR SELECT TO public USING ((location_id = my_location()));

-- POLICY admin manages schedules
CREATE POLICY "admin manages schedules" ON public.staff_schedules AS PERMISSIVE FOR ALL TO public USING ((my_role() = 'admin'::app_role)) WITH CHECK ((my_role() = 'admin'::app_role));

-- POLICY schedules visible at location
CREATE POLICY "schedules visible at location" ON public.staff_schedules AS PERMISSIVE FOR SELECT TO public USING ((EXISTS ( SELECT 1
   FROM staff_members s
  WHERE ((s.id = staff_schedules.staff_id) AND (s.location_id = my_location())))));

-- POLICY staff clock own shift
CREATE POLICY "staff clock own shift" ON public.staff_shifts AS PERMISSIVE FOR INSERT TO public WITH CHECK (((staff_id = my_staff_id()) OR (my_role() = ANY (ARRAY['manager'::app_role, 'admin'::app_role]))));

-- POLICY staff close own shift
CREATE POLICY "staff close own shift" ON public.staff_shifts AS PERMISSIVE FOR UPDATE TO public USING (((staff_id = my_staff_id()) OR (my_role() = ANY (ARRAY['manager'::app_role, 'admin'::app_role]))));

-- POLICY staff read own or management shifts
CREATE POLICY "staff read own or management shifts" ON public.staff_shifts AS PERMISSIVE FOR SELECT TO public USING (((staff_id = my_staff_id()) OR (my_role() = ANY (ARRAY['manager'::app_role, 'admin'::app_role]))));

-- POLICY participants leave threads
CREATE POLICY "participants leave threads" ON public.thread_participants AS PERMISSIVE FOR DELETE TO public USING ((profile_id = auth.uid()));

-- POLICY participants read memberships
CREATE POLICY "participants read memberships" ON public.thread_participants AS PERMISSIVE FOR SELECT TO public USING ((is_thread_participant(thread_id) OR (my_role() = ANY (ARRAY['manager'::app_role, 'admin'::app_role]))));

-- POLICY participants update read time
CREATE POLICY "participants update read time" ON public.thread_participants AS PERMISSIVE FOR UPDATE TO public USING ((profile_id = auth.uid()));

-- POLICY thread creators add participants
CREATE POLICY "thread creators add participants" ON public.thread_participants AS PERMISSIVE FOR INSERT TO public WITH CHECK ((EXISTS ( SELECT 1
   FROM message_threads t
  WHERE ((t.id = thread_participants.thread_id) AND (t.created_by = auth.uid())))));

-- POLICY authenticated avatar reads
CREATE POLICY "authenticated avatar reads" ON storage.objects AS PERMISSIVE FOR SELECT TO authenticated USING ((bucket_id = 'avatars'::text));

-- POLICY educators upload child photos
CREATE POLICY "educators upload child photos" ON storage.objects AS PERMISSIVE FOR INSERT TO authenticated WITH CHECK (((bucket_id = 'child-photos'::text) AND (my_role() = ANY (ARRAY['staff'::app_role, 'manager'::app_role, 'admin'::app_role]))));

-- POLICY families upload linked child photos
CREATE POLICY "families upload linked child photos" ON storage.objects AS PERMISSIVE FOR INSERT TO authenticated WITH CHECK (((bucket_id = 'child-photos'::text) AND (my_role() = 'parent'::app_role) AND can_access_child(((storage.foldername(name))[1])::uuid)));

-- POLICY participants read thread attachments
CREATE POLICY "participants read thread attachments" ON storage.objects AS PERMISSIVE FOR SELECT TO authenticated USING (((bucket_id = 'message-attachments'::text) AND (is_thread_participant(((storage.foldername(name))[2])::uuid) OR (my_role() = ANY (ARRAY['manager'::app_role, 'admin'::app_role])))));

-- POLICY participants upload thread attachments
CREATE POLICY "participants upload thread attachments" ON storage.objects AS PERMISSIVE FOR INSERT TO authenticated WITH CHECK (((bucket_id = 'message-attachments'::text) AND (is_thread_participant(((storage.foldername(name))[2])::uuid) OR (my_role() = ANY (ARRAY['manager'::app_role, 'admin'::app_role])))));

-- POLICY scoped child photo reads
CREATE POLICY "scoped child photo reads" ON storage.objects AS PERMISSIVE FOR SELECT TO authenticated USING (((bucket_id = 'child-photos'::text) AND can_access_child(((storage.foldername(name))[1])::uuid)));

-- POLICY users update own avatar
CREATE POLICY "users update own avatar" ON storage.objects AS PERMISSIVE FOR UPDATE TO authenticated USING (((bucket_id = 'avatars'::text) AND ((storage.foldername(name))[1] = (auth.uid())::text)));

-- POLICY users upload own avatar
CREATE POLICY "users upload own avatar" ON storage.objects AS PERMISSIVE FOR INSERT TO authenticated WITH CHECK (((bucket_id = 'avatars'::text) AND ((storage.foldername(name))[1] = (auth.uid())::text)));

-- STORAGE BUCKETS (metadata only; object data excluded)
-- avatars | public=false | limit=null | mime=null
-- child-photos | public=false | limit=null | mime=null
-- message-attachments | public=false | limit=null | mime=null

-- REALTIME PUBLICATION TABLES
-- public.announcements
-- public.attendance
-- public.children
-- public.classrooms
-- public.daily_logs
-- public.incident_reports
-- public.invoices
-- public.message_threads
-- public.messages
-- public.notifications
-- public.payment_methods
-- public.payroll_records
-- public.photo_posts
-- public.profiles
-- public.staff_classrooms
-- public.staff_members
-- public.staff_schedules
-- public.staff_shifts
-- public.thread_participants
