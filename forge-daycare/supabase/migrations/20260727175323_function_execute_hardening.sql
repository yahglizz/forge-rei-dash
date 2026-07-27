-- Keep signed-out clients from invoking authenticated location changes.
revoke execute on function public.set_active_location(uuid) from public, anon;
grant execute on function public.set_active_location(uuid) to authenticated;

-- This function is called by a trigger, never directly by application clients.
revoke execute on function public.notify_coin_transaction_guardian() from public, anon, authenticated;
grant execute on function public.notify_coin_transaction_guardian() to service_role;
