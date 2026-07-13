-- Reconcile features that were applied during the 2026-07-13 live cutover but
-- were only described (not defined) by the tracked migration history.
-- This migration is intentionally idempotent and contains no application data.

alter table public.messages
  add column if not exists reactions jsonb not null default '[]'::jsonb,
  add column if not exists attachment_path text;

alter table public.messages alter column body set default '';
alter table public.messages drop constraint if exists messages_body_check;

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.messages'::regclass
      and conname = 'messages_body_or_attachment_check'
  ) then
    alter table public.messages
      add constraint messages_body_or_attachment_check
      check (length(body) <= 4000 and (length(trim(body)) > 0 or attachment_path is not null));
  end if;
end $$;

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.messages'::regclass
      and conname = 'messages_attachment_thread_path_check'
  ) then
    alter table public.messages
      add constraint messages_attachment_thread_path_check
      check (attachment_path is null or attachment_path like ('chat/' || thread_id::text || '/%'));
  end if;
end $$;

create or replace function public.notify_announcement_audience() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  insert into public.notifications (profile_id, kind, title, body, link)
  select p.id, 'announcement', new.title, left(new.body, 500), '/dashboard?view=announcements'
  from public.profiles p
  where p.location_id = new.location_id
    and p.active
    and p.id is distinct from new.author_id
    and (
      new.audience = 'everyone'
      or (new.audience = 'parents' and p.role = 'parent')
      or (new.audience = 'staff' and p.role in ('staff', 'manager', 'admin'))
    );
  return new;
end $$;

drop trigger if exists announcement_audience_notification on public.announcements;
create trigger announcement_audience_notification
after insert on public.announcements
for each row execute function public.notify_announcement_audience();

revoke execute on function public.notify_announcement_audience() from anon, authenticated, public;

insert into storage.buckets (id, name, public)
values ('message-attachments', 'message-attachments', false)
on conflict (id) do update set public = false;

drop policy if exists "participants read thread attachments" on storage.objects;
drop policy if exists "thread attachment reads" on storage.objects;
create policy "thread attachment reads" on storage.objects for select to authenticated
using (
  bucket_id = 'message-attachments'
  and (storage.foldername(name))[1] = 'chat'
  and public.is_thread_participant(((storage.foldername(name))[2])::uuid)
);

drop policy if exists "participants upload thread attachments" on storage.objects;
drop policy if exists "thread attachment uploads" on storage.objects;
create policy "thread attachment uploads" on storage.objects for insert to authenticated
with check (
  bucket_id = 'message-attachments'
  and (storage.foldername(name))[1] = 'chat'
  and public.is_thread_participant(((storage.foldername(name))[2])::uuid)
);

drop policy if exists "participants leave threads" on public.thread_participants;
create policy "participants leave threads" on public.thread_participants for delete
using (profile_id = auth.uid());

do $$
begin
  alter publication supabase_realtime add table public.daily_logs;
exception when duplicate_object then null;
end $$;
