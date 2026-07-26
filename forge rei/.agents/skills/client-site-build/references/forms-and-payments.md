# Forms, booking and payments

The inquiry path is the product. Everything else on the site exists to get
someone to use it. It deserves more paranoia than the design does.

## Contents

- [The rule about secrets](#the-rule-about-secrets)
- [Static form services](#static-form-services-the-zero-backend-option)
- [Verify the destination](#verify-the-destination-really)
- [The checkout modal pattern](#the-checkout-modal-pattern)
- [Two doors, always](#two-doors-always)
- [Upgrading to a real backend](#upgrading-to-a-real-backend)

---

## The rule about secrets

**A secret key in client-side JavaScript is public.** Not obscured — public.
Anyone can read it in view-source and use it.

- A mail API key (`re_…`) lets a stranger send email as the client's domain and
  get it blacklisted.
- A payments secret key (`sk_…`) is account access.

On a static site this means: anything requiring a secret goes behind a serverless
function, with the key in an environment variable. There is no clever middle
ground. If you find yourself reasoning toward putting a secret in the client
because the site has no backend, the correct conclusion is that the site now
needs a backend.

Public/publishable keys (`pk_…`) and form-service access keys are designed to be
visible — but see the abuse note below.

---

## Static form services (the zero-backend option)

Services like Web3Forms take a client-side POST and email the submission. Free,
no backend, work fine on a static host.

```js
await fetch('https://api.web3forms.com/submit', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
  body: JSON.stringify({
    access_key: KEY,
    subject: `New inquiry — ${plan.title}`,
    name, email, phone,
    package: `${plan.title} — ${plan.price}`,
    message: note,
  }),
});
```

Two things to understand about them:

**The destination inbox is set in their dashboard, not in your code.** It cannot
be confirmed by reading the repo. The `email` field in the payload is the
*sender/reply-to*, not the recipient. Write down the verified destination
somewhere durable, because the next person to read the code cannot derive it.

**The access key is visible, so the endpoint is abusable.** Anyone can read it
and spam the form. Acceptable at low volume; add a honeypot field and an origin
check when it matters, which requires a function.

---

## Verify the destination (really)

Two independent checks. Both are necessary; neither is sufficient.

### 1. Can the domain receive mail at all?

```bash
dig +short MX <domain>
```

Empty output means **no**. Not "misconfigured" — the domain cannot receive email,
full stop. This is the check that would have caught the ClientForge bug, where
the site published `…@atouchofblessings.com` (plural, no MX) while the live
domain was `…@atouchofblessing.com` (singular, Google MX). Every mailto click
and every reply-to bounced.

Run it against the contact address, the reply-to, and any address the client
gives you. Clients typo their own domains constantly, and a one-letter difference
is invisible in review.

### 2. Does a real submission arrive?

Send a clearly-labelled test through **each** path — contact form, package
reservation, booking request — and have the operator confirm receipt. A `200` and
`success: true` mean the service accepted it, not that a human received it.

Label them so they're obviously not real leads (`[TEST 1/3] …`) and tell the
operator to delete them after.

---

## The checkout modal pattern

When someone picks a package, **open a modal right there**. Scrolling them to a
generic contact form loses the context of what they chose and adds a step at the
exact moment they were ready.

- Carry the chosen package into the modal and into the submission, so the
  inquiry says what they picked and at what price.
- Show what's included and the delivery promise again — this is the moment of
  commitment and reassurance is worth more than brevity.
- Close on Escape, on backdrop click, and with a visible control. Lock body
  scroll while open and restore focus to whatever opened it.
- **Never imply a card was charged when no payment was taken.** "Nothing has been
  charged — we'll confirm scope and send a payment link" is honest and converts
  fine. Implying otherwise is fraud.

For managed services where the client pays a platform directly (ad spend), say so
**on the card and in the modal**, and record it in the submission. Somebody
reaching a payment step thinking spend is included is a dispute waiting to
happen.

---

## Two doors, always

Next to the buy action, offer a low-commitment one: *see the work first / book a
short call*. Some fraction of ready buyers need reassurance before money, and
without that door they leave and don't come back.

Same modal, different mode — the booking variant drops price and scope and asks
what they'd like to see.

---

## Upgrading to a real backend

The trigger is usually payments. Once checkout exists you have a serverless
function, and moving email onto it costs almost nothing extra. Do both at once
rather than migrating email on its own.

What you gain:

- **Mail from the client's own domain** with their SPF/DKIM, instead of a form
  service's infrastructure — materially better inbox placement.
- **An instant autoresponder.** For a lead-gen business this is often the single
  highest-value addition: someone who just reserved a build gets acknowledgment in
  seconds instead of silence.
- **Origin checks, honeypots and rate limiting**, impossible while the key is public.
- **Logs and retries** — you can see that mail sent rather than assuming.

The DNS step is the one that can break the client's existing email:

**SPF allows exactly one TXT record per domain**, with a 10-lookup limit. A new
sender's SPF must be **merged into** the existing record, never added as a second
one. Two SPF records is a permanent error state that can break all their mail.
DKIM records are separate and additive, so those are safe.

Keys live in host environment variables, read only by the function. Never in the
repo, never in the client bundle, never in chat.
