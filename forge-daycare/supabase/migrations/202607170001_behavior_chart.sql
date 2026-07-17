-- Behavior chart: classic red/yellow/green clip chart, one row per MOVE.
-- The chart "resets daily" for free — a day's color is the newest event for
-- that behavior_date, and a day with no events reads as green. Append-only
-- rows keep the full move history for the parent-facing detail view.

create table public.behavior_events (
  id uuid primary key default gen_random_uuid(),
  child_id uuid not null references public.children(id) on delete cascade,
  behavior_date date not null default current_date,
  color text not null check (color in ('green', 'yellow', 'red')),
  note text,
  recorded_by uuid references public.profiles(id) on delete set null,
  created_at timestamptz not null default now()
);

create index behavior_events_child_day on public.behavior_events (child_id, behavior_date);

alter table public.behavior_events enable row level security;

-- Same scoping as daily_logs: parents see their children, staff their
-- classrooms, management the whole location.
create policy "scoped behavior read" on public.behavior_events
  for select using (public.can_access_child(child_id));

-- Only the care team moves the chart, and only for children they can access.
create policy "educators write behavior" on public.behavior_events
  for insert with check (
    public.my_role() in ('staff', 'manager', 'admin')
    and public.can_access_child(child_id)
    and recorded_by = auth.uid()
  );

-- Append-only by design: no update/delete policies. A wrong tap is corrected
-- by tapping the right color (a newer event), preserving the audit trail.

do $$
begin
  alter publication supabase_realtime add table public.behavior_events;
exception when duplicate_object then null;
end $$;
