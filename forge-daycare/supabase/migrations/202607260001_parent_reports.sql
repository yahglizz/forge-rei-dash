-- Parent Reports ("Concerns"): a private channel from a family to the OWNER.
-- Deliberately inverts the house rule — managers and staff get NO policy branch
-- anywhere in this file. The point of the feature is that a parent can raise
-- something ABOUT the center (a manager, a bill, a safety worry) and only the
-- admin/owner sees it. That boundary is enforced here, not in the UI.
-- Threaded both ways; the owner triages new -> in_review -> resolved.

create table public.parent_reports (
  id uuid primary key default gen_random_uuid(),
  location_id uuid not null references public.locations(id),
  author_id uuid not null references public.profiles(id) on delete cascade,
  child_id uuid references public.children(id) on delete set null,
  subject text not null check (length(trim(subject)) > 0 and length(subject) <= 200),
  body text not null check (length(trim(body)) > 0 and length(body) <= 4000),
  attachment_path text,
  status text not null default 'new' check (status in ('new', 'in_review', 'resolved')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  -- Ties the storage object to its author, same idea as
  -- messages_attachment_thread_path_check.
  constraint parent_reports_attachment_path_check
    check (attachment_path is null or attachment_path like (author_id::text || '/%'))
);

create table public.parent_report_replies (
  id uuid primary key default gen_random_uuid(),
  report_id uuid not null references public.parent_reports(id) on delete cascade,
  author_id uuid not null references public.profiles(id) on delete cascade,
  body text not null check (length(trim(body)) > 0 and length(body) <= 4000),
  created_at timestamptz not null default now()
);

create index parent_reports_inbox on public.parent_reports (location_id, created_at desc);
create index parent_reports_author on public.parent_reports (author_id, created_at desc);
create index parent_report_replies_report on public.parent_report_replies (report_id, created_at);

alter table public.parent_reports enable row level security;
alter table public.parent_report_replies enable row level security;

-- Both branches read plain columns of the new row, so INSERT ... RETURNING
-- survives (the trap that needed 202607190001 and 202607230001).
create policy "author and owner read reports" on public.parent_reports for select
  using (
    author_id = auth.uid()
    or (public.my_role() = 'admin' and location_id = public.my_location())
  );

create policy "parents file reports" on public.parent_reports for insert
  with check (
    public.my_role() = 'parent'
    and author_id = auth.uid()
    and location_id = public.my_location()
    and (child_id is null or public.can_access_child(child_id))
  );

create policy "owner triages reports" on public.parent_reports for update
  using (public.my_role() = 'admin' and location_id = public.my_location())
  with check (public.my_role() = 'admin' and location_id = public.my_location());
-- No delete policy: a report is a record.

-- Column protection RLS cannot express: the owner may move `status`, nothing
-- else. Same silent-clamp shape as guard_message_update.
create or replace function public.guard_parent_report_update() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  new.location_id := old.location_id;
  new.author_id := old.author_id;
  new.child_id := old.child_id;
  new.subject := old.subject;
  new.body := old.body;
  new.attachment_path := old.attachment_path;
  new.created_at := old.created_at;
  return new;
end $$;
revoke execute on function public.guard_parent_report_update() from anon, authenticated, public;

drop trigger if exists parent_report_update_guard on public.parent_reports;
create trigger parent_report_update_guard before update on public.parent_reports
for each row execute function public.guard_parent_report_update();

-- Alphabetically after the guard, so updated_at still moves.
drop trigger if exists parent_reports_touch on public.parent_reports;
create trigger parent_reports_touch before update on public.parent_reports
for each row execute function public.touch_updated_at();

-- Replies inherit the report's visibility. The subquery runs as the CALLER, so
-- parent_reports' own RLS is enforced inside it — one rule, stated once. A
-- security-definer helper would bypass that RLS and force us to restate it.
create policy "report participants read replies" on public.parent_report_replies for select
  using (
    exists (select 1 from public.parent_reports r where r.id = parent_report_replies.report_id)
  );

create policy "report participants reply" on public.parent_report_replies for insert
  with check (
    author_id = auth.uid()
    and exists (select 1 from public.parent_reports r where r.id = parent_report_replies.report_id)
  );
-- No update/delete: replies are immutable, like messages and coin_transactions.

-- Owner-scoped object keys (<author_profile_id>/<uuid>-<name>), same shape as
-- the avatars bucket — avoids uploading against a report id that does not exist
-- yet at the time the parent picks the photo.
insert into storage.buckets (id, name, public)
values ('report-attachments', 'report-attachments', false)
on conflict (id) do update set public = false;

drop policy if exists "report attachment uploads" on storage.objects;
create policy "report attachment uploads" on storage.objects for insert to authenticated
with check (
  bucket_id = 'report-attachments'
  and (storage.foldername(name))[1] = auth.uid()::text
);

drop policy if exists "report attachment reads" on storage.objects;
create policy "report attachment reads" on storage.objects for select to authenticated
using (
  bucket_id = 'report-attachments'
  and (
    (storage.foldername(name))[1] = auth.uid()::text
    or (public.my_role() = 'admin' and exists (
      select 1 from public.profiles p
      where p.id = ((storage.foldername(name))[1])::uuid
        and p.location_id = public.my_location()
    ))
  )
);

do $$
begin
  alter publication supabase_realtime add table public.parent_reports;
exception when duplicate_object then null;
end $$;

do $$
begin
  alter publication supabase_realtime add table public.parent_report_replies;
exception when duplicate_object then null;
end $$;
