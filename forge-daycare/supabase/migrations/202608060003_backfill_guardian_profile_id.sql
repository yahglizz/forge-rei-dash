-- Child -> parent linkage lives in two places: children.guardian_profile_id (what
-- enrollment writes and what every screen reads) and the legacy guardian_children
-- join table (seed data only -- no app code reads or writes it). can_access_child()
-- honours both, so parents could see their child while the app could not name the
-- guardian, leaving "message this child's parent" with nobody to send to.
--
-- Collapse onto the column the app actually uses. Legacy rows are left in place;
-- nothing reads them, and dropping the table is a separate decision.
update public.children c
set guardian_profile_id = g.profile_id
from public.guardian_children gc
join public.guardians g on g.id = gc.guardian_id
join public.profiles p on p.id = g.profile_id
where gc.child_id = c.id
  and c.guardian_profile_id is null
  and p.location_id = c.location_id   -- never link a guardian across centers
  and p.active;
