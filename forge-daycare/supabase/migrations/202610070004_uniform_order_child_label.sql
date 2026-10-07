-- 202610070004_uniform_order_child_label.sql
--
-- 1. Staff of a centre may read every uniform order of that centre (202610070002 widened the SELECT
--    policy), but `children` RLS only shows staff the children of THEIR OWN classrooms, so the staff
--    queue could not name the child or the classroom for any other classroom. The order now carries
--    a snapshot of both, filled by a trigger at insert time (no client write path, and
--    create_uniform_order / redeem_uniform_with_coins are not redefined).
-- 2. Child-photo avatar DELETE policy (202610070003): the ::uuid cast was guarded only by an 8-hex
--    prefix check, and SQL does not promise AND / CASE evaluation order for a malformed name, so a
--    name like '12345678-zzzz/avatar-x' could raise instead of matching nothing. The cast now sits
--    inside a CASE that first checks the FULL uuid pattern.

-- 1. Order labels. Table-level SELECT is already granted to clients and there is no INSERT / UPDATE
-- grant or policy, so the new columns are read-only for every client role.
alter table public.uniform_orders
  add column if not exists child_label text,
  add column if not exists classroom_name text;

create or replace function public.uniform_order_fill_labels()
returns trigger
language plpgsql
security definer
set search_path to 'public'
as $$
begin
  -- Always recomputed from the child (never trusted from the inserted row).
  select nullif(btrim(c.first_name || case when nullif(btrim(c.last_name), '') is not null
                                           then ' ' || upper(left(btrim(c.last_name), 1)) || '.' else '' end), ''),
         cl.name
    into new.child_label, new.classroom_name
    from public.children c
    left join public.classrooms cl on cl.id = c.classroom_id
   where c.id = new.child_id;
  return new;
end $$;
revoke all on function public.uniform_order_fill_labels() from public, anon, authenticated;

drop trigger if exists uniform_order_labels on public.uniform_orders;
create trigger uniform_order_labels before insert on public.uniform_orders
  for each row execute function public.uniform_order_fill_labels();

-- Backfill existing orders.
update public.uniform_orders o
   set child_label = nullif(btrim(c.first_name || case when nullif(btrim(c.last_name), '') is not null
                                                       then ' ' || upper(left(btrim(c.last_name), 1)) || '.' else '' end), ''),
       classroom_name = cl.name
  from public.children c
  left join public.classrooms cl on cl.id = c.classroom_id
 where c.id = o.child_id and o.child_label is null;

-- 2. Avatar DELETE policy, cast made safe. Same semantics otherwise: <child uuid>/avatar-* files of a
-- child the caller can access, in the child-photos bucket.
drop policy if exists "family and staff delete child avatar files" on storage.objects;
create policy "family and staff delete child avatar files" on storage.objects
  for delete to authenticated
  using (
    bucket_id = 'child-photos'
    and name ~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/avatar-[^/]+$'
    and public.can_access_child(
      case when name ~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/avatar-[^/]+$'
           then ((storage.foldername(name))[1])::uuid end)
  );
