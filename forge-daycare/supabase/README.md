# Supabase change control

Supabase is the authoritative datastore for the daycare app and the FORGE management workspace. The migrations in this folder are source-controlled review artifacts; they are not permission to mutate the live project automatically.

## 2026-07-14 hardening sequence

1. Capture and review the no-row live snapshot described in `snapshots/20260714-pre-hardening/README.md`.
2. Review `202607140001_reconcile_live_features.sql`, which makes the tracked history match the known live messaging, announcement, storage, and realtime features.
3. Review `202607140002_security_finance_hardening.sql`, which closes tenant/role policy gaps, adds center settings, creates the authoritative payment ledger contract, and adds transaction-safe finance RPCs.
4. Apply to a branch or disposable Supabase project and run the two-location role matrix before production.
5. Apply to production only after the FORGE and Next app clients use the documented RPCs.
6. Deploy `functions/provision-user` only after its database dependencies exist and its exact allowed origins are configured.

Never add row/PII dumps, access tokens, service-role keys, database passwords, fixed PINs, or seed credentials to this directory.

## Finance contract

- `public.payments` is authoritative. `public.invoices.payments` is retained only as a deprecated compatibility column.
- Clients cannot insert ledger rows directly.
- `record_invoice_payment(...)` atomically validates the signed-in manager/admin or invoice owner, inserts an idempotent manual/Stripe-ready ledger row, and marks a fully covered invoice paid.
- `mark_payroll_paid(...)` atomically verifies management access at the staff member's location and records paid status, timestamp, and optional reference.

## Provisioning contract

The `provision-user` Edge Function accepts only `ensure-guardian` and `create-staff`. It derives location from the active management caller, validates classrooms against that location, uses the database Login ID allocator, and generates a random PIN. It has no seed action.
