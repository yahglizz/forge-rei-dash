-- Restore the baseline set by 20260806042900_function_execute_hardening: trigger
-- functions are not API surface.
--
-- Supabase grants EXECUTE on every new function in `public` to anon and authenticated,
-- and exposes it at /rest/v1/rpc/<name>. The hardening migration revoked that across the
-- board, but four trigger functions created afterwards — three in 202608070001
-- (time clock) and one in 202608080001 (sign-in sheets) — were never covered, so they
-- came back callable, `guard_attendance_signature` and the three shift guards even by
-- `anon`.
--
-- Calling a plpgsql trigger function directly fails with "trigger functions can only be
-- called as triggers", so this is not a live hole today. It is fixed anyway because the
-- next trigger function written in SQL rather than plpgsql, or given a non-trigger
-- return type, would be a hole — and because a baseline that silently stops applying to
-- new code is not a baseline.

revoke all on function public.guard_attendance_signature() from public, anon, authenticated;
revoke all on function public.guard_staff_shift_insert()   from public, anon, authenticated;
revoke all on function public.guard_staff_shift_update()   from public, anon, authenticated;
revoke all on function public.log_staff_shift_edit()       from public, anon, authenticated;
