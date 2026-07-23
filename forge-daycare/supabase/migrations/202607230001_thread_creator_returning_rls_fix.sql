-- Fix: a PARENT could never start a conversation. The app's New Message flow does
--   insert into message_threads ... returning id   (PostgREST return=representation)
-- and PostgREST evaluates the SELECT policy on the returned row. "participants read
-- threads" is
--   is_thread_participant(id) OR (manager/admin AND location_id = my_location())
-- and at the instant the thread row is created it has no participants yet -- the
-- thread_participants rows are inserted on the NEXT statement. So the RETURNING clause
-- was rejected with 42501 and the whole flow aborted before any participant or message
-- was written. Managers and admins never saw it because their role branch satisfies the
-- policy without participation; parents have no such branch, so for them the button was
-- simply dead.
--
-- Same class as 202607190001 (children RETURNING RLS): add a branch that reads a plain
-- column of the NEW row instead of a self-referential lookup that cannot see it yet.
-- created_by = auth.uid() widens nothing in practice -- the creator adds themselves as a
-- participant microseconds later and would see the thread anyway. Participant scoping and
-- management oversight are unchanged.

drop policy if exists "participants read threads" on public.message_threads;

create policy "participants read threads" on public.message_threads
  for select
  using (
    public.is_thread_participant(id)
    or created_by = auth.uid()
    or (
      public.my_role() = any (array['manager'::app_role, 'admin'::app_role])
      and location_id = public.my_location()
    )
  );
