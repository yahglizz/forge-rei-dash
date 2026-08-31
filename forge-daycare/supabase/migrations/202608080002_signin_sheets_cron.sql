-- Nightly dispatcher for the sign-in sheet PDFs.
--
-- Runs hourly and asks each location "is it 8 PM where YOU are?" rather than
-- scheduling one UTC time. Eastern is UTC-5 in winter and UTC-4 in summer, so a
-- fixed UTC cron would silently drift an hour twice a year and file the sheet
-- against the wrong day. Reading the hour in the location's own timezone is
-- immune to that, and it keeps working unchanged if a second center is ever
-- opened in another zone.
--
-- Secrets live in vault, not here — this file is committed. Create them once:
--   select vault.create_secret('https://<ref>.supabase.co/functions/v1/generate-signin-sheets', 'signin_sheets_fn_url');
--   select vault.create_secret(encode(gen_random_bytes(32), 'hex'), 'signin_sheets_cron_secret');
--   select vault.create_secret('<publishable/anon key>', 'signin_sheets_anon_key');
-- The cron_secret value must ALSO be set as the SIGNIN_SHEETS_CRON_SECRET env var on
-- the edge function (Dashboard → Edge Functions → Secrets). The function fails closed
-- if that var is unset, so the schedule stays inert until it is — which is the correct
-- direction to fail, but it does mean nothing is archived until you set it.

create or replace function public.dispatch_signin_sheets(p_force boolean default false)
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  fn_url    text;
  secret    text;
  anon_key  text;
  headers   jsonb;
  loc       record;
  local_now timestamp;
  today     date;
  fired     integer := 0;
begin
  select decrypted_secret into fn_url   from vault.decrypted_secrets where name = 'signin_sheets_fn_url';
  select decrypted_secret into secret   from vault.decrypted_secrets where name = 'signin_sheets_cron_secret';
  select decrypted_secret into anon_key from vault.decrypted_secrets where name = 'signin_sheets_anon_key';

  -- Fail closed and loudly. A dispatcher that quietly does nothing for a month is
  -- worse than one that errors, because the gap only surfaces when an auditor asks
  -- for a sheet that was never generated.
  if fn_url is null or secret is null or anon_key is null then
    raise warning 'dispatch_signin_sheets: vault secrets missing — nothing dispatched';
    return 0;
  end if;

  -- The Authorization header satisfies the platform's verify_jwt gate; x-cron-secret is
  -- what the function itself authorizes on. Keeping verify_jwt enabled means an
  -- unauthenticated caller is turned away before any of our code runs.
  headers := jsonb_build_object(
    'Content-Type',   'application/json',
    'Authorization',  'Bearer ' || anon_key,
    'x-cron-secret',  secret
  );

  for loc in select id, timezone from public.locations loop
    local_now := now() at time zone loc.timezone;
    today     := local_now::date;

    if p_force or extract(hour from local_now) = 20 then
      perform net.http_post(
        url := fn_url, headers := headers,
        body := jsonb_build_object('location_id', loc.id, 'kind', 'daily', 'date', today)
      );
      fired := fired + 1;

      -- Friday also produces the Mon–Fri grid, which is the sheet that carries the
      -- per-child weekly hour total. A daily sheet has nowhere to put a week total.
      if extract(isodow from today) = 5 then
        perform net.http_post(
          url := fn_url, headers := headers,
          body := jsonb_build_object('location_id', loc.id, 'kind', 'weekly', 'date', today)
        );
        fired := fired + 1;
      end if;
    end if;
  end loop;

  return fired;
end $$;

-- Nobody should be able to trigger center-wide generation from a browser session.
revoke all on function public.dispatch_signin_sheets(boolean) from public, anon, authenticated;

-- Hourly on the hour; the function itself decides which locations are due.
select cron.unschedule('signin-sheets-nightly')
where exists (select 1 from cron.job where jobname = 'signin-sheets-nightly');

select cron.schedule('signin-sheets-nightly', '0 * * * *', $$select public.dispatch_signin_sheets()$$);
