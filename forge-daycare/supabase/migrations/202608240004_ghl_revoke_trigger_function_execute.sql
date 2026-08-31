-- Same baseline as 202608170003: trigger functions are not API surface.
--
-- Supabase grants EXECUTE on every new function in `public` to anon and authenticated
-- and exposes it at /rest/v1/rpc/<name>, so the four enqueue triggers added by
-- 202608240001 came back callable — by `anon` as well. Calling a plpgsql trigger
-- function directly fails with "trigger functions can only be called as triggers", so
-- this is not a live hole, but it is fixed for the same reason the last one was: the
-- baseline has to keep applying to new code to mean anything.
revoke all on function public.ghl_enqueue_message()             from public, anon, authenticated;
revoke all on function public.ghl_enqueue_incident()            from public, anon, authenticated;
revoke all on function public.ghl_enqueue_parent_report()       from public, anon, authenticated;
revoke all on function public.ghl_enqueue_parent_report_reply() from public, anon, authenticated;
