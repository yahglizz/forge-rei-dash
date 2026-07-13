-- Preserve the difference between an incident being recorded and a manager
-- confirming that the family was directly notified.
alter table public.incident_reports
  alter column parent_notified_at drop not null;
