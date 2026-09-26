-- 202609260010_ghl_unlinked_families_definer.sql
--
-- 2026-09-26 E2E pass. The owner dashboard's "CRM sync status" card showed "Couldn't check
-- the CRM queue" for every owner: ghl_unlinked_families is a security_invoker view that
-- selects profiles.phone, and 202609120003 revoked that column from `authenticated`, so every
-- read failed with 42501 permission denied (PostgREST 403). The revoke was right; the view
-- just can't read through it as the caller.
--
-- Same shape as guardian_contacts() (202609230001): run as the view owner, and put the
-- access rule the invoker's RLS used to supply into the view itself — admins only, only
-- for the center they are standing in (exactly the ghl_outbox "admin reads ghl outbox"
-- policy). Families, staff and managers get zero rows, and the phone column stays revoked
-- on profiles for them.

create or replace view public.ghl_unlinked_families
with (security_invoker = false) as
select p.id as profile_id,
       p.location_id,
       p.display_name,
       p.phone,
       count(o.id) filter (where o.status = 'skipped') as waiting_items,
       max(o.created_at) as last_attempt
from public.profiles p
join public.ghl_outbox o on o.profile_id = p.id
left join public.ghl_contact_links l on l.profile_id = p.id
where p.role = 'parent'
  and l.profile_id is null
  and public.my_role() = 'admin'
  and o.location_id = public.my_location()
group by p.id, p.location_id, p.display_name, p.phone;

revoke all on public.ghl_unlinked_families from anon, authenticated;
grant select on public.ghl_unlinked_families to authenticated, service_role;
