-- 202609260001_pass_season1_garden_ranks.sql
--
-- Owner-approved 2026-09-26 (Yahjair):
-- 1. Lifetime ranks move from the placeholder military names to the garden -> sky ladder
--    at every center. Only rows still carrying the original default name are renamed, so a
--    name the owner already edited in the dashboard is left alone.
-- 2. Season 1 "Harvest of Blessings" (Oct 1 - Dec 31, 2026) at A Touch of Blessings and
--    A Touch of Blessings 2 with the 20-level track from CODEX_BLESSINGS_PASS_UI.md.
--    NOT at A Mother's Touch (4444): separate legal entity, its perks need its own OK.
--    Level 15 (tuition credit) is left out until the owner sets the amount; add it from
--    the dashboard's Season setup.

update public.pass_ranks r set name = v.new_name
from (values
  (0, 'Recruit', 'Little Seed'), (20, 'Cadet', 'Sprout'), (50, 'Corporal', 'Seedling'),
  (100, 'Sergeant', 'Bud'), (175, 'Lieutenant', 'Blossom'), (250, 'Captain', 'Sunflower'),
  (350, 'Major', 'Rising Star'), (500, 'Colonel', 'Shining Star'), (700, 'General', 'Superstar'),
  (1000, 'Legend', 'Blessings Legend')
) v(min_days, old_name, new_name)
where r.min_days = v.min_days and r.name = v.old_name;

with seasons as (
  insert into public.pass_seasons (location_id, name, starts_on, ends_on, xp_per_level, max_level)
  select l.id, 'Harvest of Blessings', date '2026-10-01', date '2026-12-31', 400, 20
  from public.locations l
  where l.id in ('11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222')
    and not exists (
      select 1 from public.pass_seasons s
      where s.location_id = l.id and s.name = 'Harvest of Blessings' and s.starts_on = date '2026-10-01'
    )
  returning id
)
insert into public.pass_rewards (season_id, level, kind, coin_amount, title, description)
select s.id, t.level, t.kind, t.coin_amount, t.title, t.description
from seasons s
cross join (values
  (1,  'coins', 10,   '10 Blessing Coins', 'Welcome to the season!'),
  (2,  'coins', 15,   '15 Blessing Coins', 'A little something for showing up.'),
  (3,  'prize', null, 'Harvest sticker sheet', 'A sheet of fall stickers to take home.'),
  (4,  'coins', 20,   '20 Blessing Coins', null),
  (5,  'prize', null, 'Line Leader for a day', 'Leads the line to lunch, the playground and pick-up.'),
  (6,  'coins', 20,   '20 Blessing Coins', null),
  (7,  'prize', null, 'Pick the class song', 'Chooses the song for circle time.'),
  (8,  'coins', 25,   '25 Blessing Coins', null),
  (9,  'prize', null, 'Show & Tell spotlight', 'Brings something special from home to share with the class.'),
  (10, 'prize', null, 'Free lunch', 'Lunch is on us for a day. We''ll set the day with you.'),
  (11, 'coins', 25,   '25 Blessing Coins', null),
  (12, 'prize', null, 'Helper of the Day', 'Teacher''s right hand for a whole day.'),
  (13, 'coins', 30,   '30 Blessing Coins', null),
  (14, 'prize', null, 'Star Wall photo', 'Their photo goes up on the classroom Star Wall for a week.'),
  (16, 'coins', 30,   '30 Blessing Coins', null),
  (17, 'prize', null, 'Pick the class game', 'Chooses the game for outdoor play.'),
  (18, 'coins', 40,   '40 Blessing Coins', null),
  (19, 'prize', null, 'Harvest Champion certificate', 'A framed certificate to take home.'),
  (20, 'prize', null, 'Free day', 'One day of care on us. We''ll schedule it with you.')
) t(level, kind, coin_amount, title, description);
