# provision-user

Management-only Supabase Edge Function for creating guardian and staff Auth accounts.

The function requires a signed-in, active `manager` or `admin`, derives the location from that caller, validates all classroom assignments against the location, and returns a cryptographically generated PIN only when an account is first created. It contains no seed operation or embedded credentials.

Required Edge Function secrets/configuration:

- `SUPABASE_URL` (provided by Supabase)
- `SUPABASE_ANON_KEY` (provided by Supabase)
- `SUPABASE_SERVICE_ROLE_KEY` (provided by Supabase; never expose it to a client)
- `LOGIN_DOMAIN` (optional; defaults to the app's synthetic login domain)
- `ALLOWED_ORIGINS` (comma-separated exact browser origins; include `app://local` for the iOS wrapper)

Request contracts:

```json
{"action":"ensure-guardian","email":"guardian@example.com","first_name":"First","last_name":"Last"}
```

```json
{"action":"create-staff","first_name":"First","last_name":"Last","role":"staff","job_title":"Teacher","hourly_rate":"20.00","classroom_ids":["uuid"]}
```

Do not add demo accounts, fixed PINs, or a seed action. Deploy only after the hardening migrations have been reviewed and applied.
