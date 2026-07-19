-- Fix: children INSERT ... RETURNING (PostgREST return=representation) failed with
-- 42501 "new row violates row-level security policy". The "scoped child access" SELECT
-- policy calls public.can_access_child(id), whose self-referential
--   exists (select 1 from public.children c where c.id = target ...)
-- cannot see the row being inserted within the same INSERT statement, so the RETURNING
-- clause is rejected even for a valid manager/admin. This silently broke new-child
-- enrollment (the roster was stuck at 0 children).
--
-- Add a direct management branch that reads the NEW row's location_id column instead of
-- self-querying children. Additive: management already has full SELECT access to children
-- at their location via can_access_child once the row is committed; this only closes the
-- RETURNING-visibility gap. No access is widened beyond the existing policy's intent, and
-- parent/staff scoping is unchanged (they still go through can_access_child).

drop policy if exists "scoped child access" on public.children;

create policy "scoped child access" on public.children
  for select
  using (
    public.can_access_child(id)
    or (
      public.my_role() = any (array['manager'::app_role, 'admin'::app_role])
      and location_id = public.my_location()
    )
  );
