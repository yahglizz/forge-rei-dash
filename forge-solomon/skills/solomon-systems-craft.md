---
agent: solomon
skill: systems-craft
role: The machine — what is wired, what is verified, what is broken
seed: true
priority: top
---

# Systems Craft — the lead machine, and how much of it you may trust

`daycare-context.md` holds the business. This holds the **machine that turns a stranger
into a family**: ad → pixel → website → CRM → the operator's phone → follow-up.

You brief on enrollment every day. Every enrollment claim you make rests on this chain
actually working. **A form existing is not a lead captured.** This file is how you know
the difference, and it is the only place you may source that claim from.

Verified means: someone submitted a real record end to end and watched it land. Nothing on
this page is marked verified because the code looks right.

---

## The chain, link by link

| # | Link | State | How we know |
|---|---|---|---|
| 1 | Meta ad → click | **Not live** | No campaign running. All 5 historical campaigns are Off. |
| 2 | Meta Pixel fires | **Verified Aug 16** | Pixel `1361417309440327`. PageView, ViewContent, Lead, Contact all returned HTTP 200 from `facebook.com/tr` on production. |
| 3 | Website enrollment form | **Verified Aug 14** | Live submission redirected to `/success`. |
| 4 | → GoHighLevel contact | **Verified Aug 14** | Landed in location `4JIvZEmkY5EjTsDRnjBN` with all three tags. |
| 5 | → Opportunity created | **Verified Aug 14** | Card created in the Enrollment pipeline. |
| 6 | → Email to the operator | **Verified Aug 14** | Delivered to management@ and yahjair@ from noreply@atouchofblessing.com. |
| 7 | → Automated response to the parent | **DOES NOT EXIST** | No workflow, no SMS. A lead sits until a human notices an email. |
| 8 | → Tour booked | **Manual** | No booking automation. |

**Links 3–6 are the strongest part of this business. Links 1, 7 and 8 are where the money
leaks.** When you triage the enrollment lane, that is the shape of the problem: capture is
solid, response is absent.

---

## The CRM, precisely

GoHighLevel sub-account **`4JIvZEmkY5EjTsDRnjBN`**.

**Contact identity is the CHILD's name, not the parent's.** Deliberate — staff look children
up by name. This has a consequence you must never get wrong:

- `{{contact.first_name}}` = **the child**
- `{{contact.parent_name}}` = **the parent** (custom field)

Any message that greets `{{contact.first_name}}` addresses a mother by her toddler's name.
Check every template you propose against this.

**Two intake pipelines, separated by tag — never confuse them:**

| Form | Tag | Meaning |
|---|---|---|
| Website enrollment inquiry | `form-type-new-inquiry` | Brand-new lead |
| Family Contact Form | `form-type-existing-family` | Current student updating info |

Website leads also carry `website-lead` plus a classroom tag derived from the child's age:
`group-infants` / `group-toddlers` / `group-prek` / `group-schoolage`.

Custom fields on record: Child Name, Child DOB, Child Age, Parent Name, Parent Relationship,
Preferred Location, Classroom Group, Enrollment Status, SMS Consent, Emergency Contact
Name/Phone/Relationship. Pipelines: **Enrollment** (6 stages) and Marketing Pipeline (11, a
leftover contractor snapshot).

---

## 🔴 Known defects — never brief around these silently

1. **GHL timezone is `America/Cancun`.** Every workflow delay, reminder and send window
   fires an hour off Philadelphia and drifts seasonally, because Cancun has no DST. Any
   scheduling you propose is wrong until this is fixed.
2. **The GHL location record is an unbranded agency template** — named "Philadelphia",
   website `clientforge.tech`, email `ymjg031122@gmail.com`, ZIP 19122 instead of 19121.
   Merge fields and templates pull from this. Anything auto-generated carries the wrong brand.
3. **GitHub → Vercel auto-deploy is broken.** A push produces no build. The site only
   updates via a manual `vercel --prod`. **Never assume a code change is live.**
4. **A2P 10DLC is not registered.** No SMS can legally send through US carriers. Any
   text-message follow-up you propose is a draft, not a plan, until this clears.
5. **The enrollment form attracts spam.** Bot submissions with foreign numbers have reached
   the CRM. Two-layer defense (timing check + US phone validation) is deployed; watch for
   leakage and discount obviously fake contacts from any count you report.
6. **The MCP connection to GHL is agency-scoped.** Contacts, pipelines and custom fields
   return 401. Location metadata reads fine. If a tool says "no contacts," that may be a
   permission artifact, not an empty CRM — say so rather than reporting zero.

---

## Advertising

- Ad account **`1175564690150627`**. Page: A Touch of Blessings Daycare (`939494549239823`).
- Lifetime history: **$46.30 spent, 2,609 impressions, 1,867 reach, 4 leads at $11.58** — all
  from Meta Instant Forms, March 2026. Those 4 leads **expired uncontacted**; Meta purges lead
  form data after 90 days and it was never downloaded.
- **Never benchmark a website-conversion campaign against that $11.58.** Instant Form leads
  are cheap and low-intent. Website leads typically cost 1.5–2.5× more and convert far better.
  Project **$18–28 CPL** and judge on **cost per tour booked**, not cost per lead.
- Pixel events available to optimize on: `Lead` (fires on `/success` — the conversion event),
  `ViewContent` (location pages), `Contact` (phone taps), `PageView`.
- Page has ~1 follower and no posts. Instagram is not connected to the Page. Both suppress
  ad performance — flag before proposing spend.
- Meta business verification is pending and may throttle delivery.

**Budget math you must apply before proposing an ad set split:** Meta needs ~50 conversions
per ad set per week to exit the learning phase. At $25/day split three ways, each ad set sees
roughly 2–3 conversions a week and never stabilizes. Either consolidate, or fund the split.

---

## Compliance rules that bind your proposals

- **SMS consent is optional and must stay optional.** Consent to marketing texts cannot be a
  condition of enrollment or any purchase — that is TCPA, and statutory damages run
  $500–$1,500 per message. The website checkbox was previously required; it was fixed.
  Never propose making it required again.
- Live legal pages: `/privacy-policy` and `/sms-terms`, both carrying the carrier-required
  mobile-data language. A2P registration depends on them staying live.
- Children's photographs are never public or used in marketing without a signed release.

---

## How you use this file

- Before any claim that a lead was captured, name which link in the chain you are relying on
  and whether it is verified. "Verified Aug 14" is grounded. "The form is on the site" is not.
- Before proposing any scheduled send, check defect #1.
- Before proposing any text message, check defect #4.
- Before reporting a contact count, check defects #5 and #6.
- Before proposing ad spend, check the budget math and the Page's social proof.
- When a defect above gets fixed, say so in the brief and strike it here — this file is
  seed-priority and `learn()` does not rewrite it. A human updates it.
