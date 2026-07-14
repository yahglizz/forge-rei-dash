-- 202607140005_locations_seed.sql
-- The centers this deployment serves. Idempotent, so it is safe to re-run and safe to
-- apply to the parent app's database (same rows, same ids -- these are the SAME centers).
--
-- Blessings 2 and 3 were briefly separate; they are ONE site, so only "2" exists.
-- Membership (profile_locations) is deliberately NOT seeded here: which human may stand
-- in which center is per-deployment operational data, not schema.
--
-- Must stay byte-identical with the parent app's copy.

insert into public.locations (id, name, timezone, opens_at, closes_at)
values
  ('11111111-1111-1111-1111-111111111111', 'A Touch of Blessings',   'America/New_York', '06:30', '18:00'),
  ('22222222-2222-2222-2222-222222222222', 'A Touch of Blessings 2', 'America/New_York', '06:30', '18:00'),
  ('44444444-4444-4444-4444-444444444444', 'A Mother''s Touch',      'America/New_York', '06:30', '18:00')
on conflict (id) do nothing;
