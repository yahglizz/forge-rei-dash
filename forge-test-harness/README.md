# forge-test-harness

Standalone CLI to drive YOUR OWN contact through the FORGE REI OS wholesale CRM for
end-to-end testing. Not part of the web app — run it from a terminal. It reads the wholesale
GHL creds from `marcus-wholesale-agent/config/ghl.env` (token never printed).

**Safe:** dry-run by default; every write/delete needs `--confirm` and prints a preview.
Every test contact is stamped with the `forge-test` tag; `cleanup` only deletes those.

```bash
cd "/Users/yg4st/forge rei dash/forge-test-harness"
python3 test_lead.py find     --phone "+1XXXXXXXXXX"
python3 test_lead.py reset    --phone "+1XXXXXXXXXX" --name "First Last" --confirm
python3 test_lead.py tag      --phone "+1XXXXXXXXXX" --tags "triage: asap,motivated: high" --confirm
python3 test_lead.py pipeline --phone "+1XXXXXXXXXX" --stage Hot --confirm
python3 test_lead.py status   --phone "+1XXXXXXXXXX"   # add --api-base http://<box>:7799 for box state
python3 test_lead.py cleanup  --phone "+1XXXXXXXXXX" --confirm
```

The reliable way to generate the inbound seller message is to **text your GHL business
number from your phone** — GHL has no API to fake an inbound. `inbound` is best-effort only.
