-- 202609230001_guardian_contacts_accessor.sql
--
-- 2026-09-23. The owner console (FORGE dashboard, daycare_supabase.py) lost every family's
-- contact details when 202609030001 + 202609120003 revoked profiles.login_id / auth_email /
-- phone from `authenticated`. Those revokes were right for families (every parent could read
-- the center's phone book) but the owner still needs them: the Login ID to hand a family,
-- the email a Stripe invoice goes to, the phone a balance reminder is texted to, and the
-- staff edit form (which otherwise saves a blank phone over the real one).
--
-- Same shape as staff_pay_rates() (202609130003): a SECURITY DEFINER accessor that answers
-- only managers/admins, only for profiles at the center they are standing in. Families and
-- staff get zero rows, so the revokes stay fully effective for them. No service-role key
-- ever leaves Supabase.

create or replace function public.guardian_contacts(p_ids uuid[])
returns table (id uuid, phone text, auth_email text, login_id text)
language sql
stable
security definer
set search_path = public
as $$
  select p.id, p.phone, p.auth_email, p.login_id
  from public.profiles p
  where p.id = any(p_ids)
    and public.my_role() in ('manager', 'admin')
    and p.location_id = public.my_location();
$$;

revoke all on function public.guardian_contacts(uuid[]) from public, anon;
grant execute on function public.guardian_contacts(uuid[]) to authenticated, service_role;
