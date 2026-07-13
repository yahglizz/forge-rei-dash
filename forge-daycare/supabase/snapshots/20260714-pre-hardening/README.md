# Pre-hardening live snapshot status

Snapshot target: Supabase project `blessings-daycare`, immediately before the 2026-07-14 reconciliation/hardening migrations.

The CLI in this checkout had no access token and was not linked, so the live snapshot was captured separately through the authenticated Supabase MCP. No migration or Edge Function was applied or deployed while preparing this work.

Captured, no-row artifacts are under `live/`:

- `schema-policy-function-storage.sql` — public schema, constraints, functions, policies, grants, publications, and storage bucket metadata.
- `provision-user.redacted.ts` — recovery evidence for the deployed function with the obsolete seed secret, fixed PINs, and concrete seed identities removed. It must not be deployed.

Before applying either `20260714` migration, an authorized operator should review the captured artifacts and add the following if a newer capture is required:

- `schema.sql`: `auth`, `public`, and `storage` DDL, including triggers and functions.
- `policies.sql`: `pg_policies` output for `public` and `storage`.
- `function_grants.sql`: function ownership and ACLs from `pg_proc`/`information_schema.routine_privileges`.
- `storage.sql`: bucket metadata and storage-object policy definitions; no object rows or paths.
- `edge-function/`: the currently deployed `provision-user` source if recoverable, with all environment values omitted.
- `migration-list.txt`: applied migration versions/names.

Suggested authenticated CLI starting point:

```sh
supabase login
supabase link --project-ref <project-ref>
supabase db dump --linked --schema auth,public,storage --file supabase/snapshots/20260714-pre-hardening/schema.sql
supabase migration list --linked > supabase/snapshots/20260714-pre-hardening/migration-list.txt
```

Use SQL queries against catalog views for policies/function grants because `db dump` alone is not an adequate authorization snapshot. Inspect every artifact for credentials and row/PII data before committing it.
