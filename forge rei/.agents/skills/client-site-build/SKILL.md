---
name: client-site-build
description: End-to-end pipeline for building and shipping a client's marketing website — intake and brainstorm, art direction, a buildless React build, working inquiry forms, real verification, and a live Vercel deploy. Use this whenever the work involves building, redesigning, pitching, planning, or scoping a website for a client or a business — including vague openers like "a barbershop wants a site", "let's build out a landing page for this client", "redesign X's website", "what should we charge for this build", "make a site for my friend's daycare", or any hero/scroll-animation/pricing-page/checkout work on a client site. Also use it when generating website hero art or scroll videos with Higgsfield, because the credit and seam discipline lives here. Built from the ClientForge build; it encodes the bugs that cost real money there, so reach for it even when the request sounds simple.
---

# Client Site Build

You are building a website that a real business will depend on for leads. The
job is not "a nice-looking page" — it is a machine that turns a stranger into a
booked call, and that keeps working after you walk away.

This skill is the pipeline. It exists because a previous build (ClientForge)
shipped a **contact address on a domain with no MX records** — every inquiry
bounced, silently, for months. Nothing in a design review catches that. The
checks in here do.

## The shape of the work

```
1. INTAKE      what business, what outcome, who pays
2. DECIDE      how ambitious the hero is — this is a money decision
3. BUILD       stack, sections, theme
4. WIRE        forms, booking, payments
5. VERIFY      the checks that catch silent failures
6. SHIP        deploy, confirm live, hand over
```

Do them in order. Steps 5 and 6 are where sites die, and they are the steps
people skip when the design looks finished.

---

## 1. Intake — before any code

Get these from the operator (they may need to ask their client). Don't start
building on guesses; a wrong answer here wastes the whole build.

- **What does the business actually sell, and what is one customer worth?**
  A $200 haircut client and a $30k roofing client need different pages. Job
  value sets how hard the page should push toward a call vs. a form.
- **What is the single action a visitor should take?** Call, book, buy, or
  submit. One primary action. Everything else is secondary.
- **What proof exists?** Photos, past work, reviews, numbers. Real proof beats
  any amount of design. If there is none, the page must be honest about being
  new — invented testimonials are fraud and will not be written.
- **Where do inquiries need to land?** An inbox, a CRM, a phone. Get the exact
  address. Verify it in step 5 — do not trust it.
- **Who owns the domain and DNS?** Determines whether you can ship to the real
  domain or a preview URL.

**Pricing the build.** If the operator asks what to charge, anchor on what the
client gets, not hours. The ClientForge ladder is a working reference: a
one-page lead-capture site, a multi-page site with CRM and booking, and a fully
custom build, at roughly a 1× / 2.3× / 4.7× spread. Managed services (ads,
automation) price as a **monthly management fee with the ad spend paid directly
by the client to the platform** — never take spend through your own account, and
say so on the page. It removes the single biggest source of client disputes.

---

## 2. Decide the hero — the money gate

The hero is where a build gets expensive. Three tiers; pick deliberately and say
which you picked and why.

| Tier | What it is | Cost | When it's right |
|---|---|---|---|
| **Static** | One strong image or a short looping video, crisp type | Free–minutes | Default. Most local businesses. Fastest to ship, easiest to keep. |
| **Scroll-scrubbed world** | A camera flight the visitor scrolls through | ~200+ AI credits, hours | Premium positioning, a business with several distinct service lines, a client who will pay for distinctiveness |
| **Interactive** | Canvas game, configurator, calculator | Hours of build | Only when the interaction *is* the pitch |

**Before spending any AI credits, state the estimate and get a yes.** Credits are
the operator's money. A full scroll-world is roughly `N images + (N or 2N−1)
videos`; at ~7 credits an image and ~36–45 a video that is 200+ for five scenes.
Say the number out loud before generating.

If the hero is a scroll-world, **read `references/scroll-world-hero.md` before
generating anything.** It contains the seam discipline, and getting seams wrong
means re-rendering at full price.

---

## 3. Build

Read `references/buildless-stack.md` for the conventions. The short version:

Static React over UMD with Tailwind from CDN, no bundler — a site a non-engineer
can host anywhere and you can debug by viewing source. **The JSX is precompiled
before it ships**, so visitors never download a compiler. Shipping
`@babel/standalone` costs every visitor 3.1 MB and is the single biggest
performance mistake available on this stack.

Section order that converts, adapt to the business:

1. **Hero** — what you do, for whom, and the one action
2. **Services / pricing** — real numbers where possible; a visible ladder
3. **Proof** — work, reviews, results
4. **Contact / booking** — the primary action again

**Theme from the artwork, not from taste.** Sample the palette out of the hero
image and drive the whole page from those variables. A page whose chrome is
sampled from its own art looks intentional; one where the art and the chrome
were chosen separately always looks stuck together. Define the palette once as
CSS custom properties and use blanket rules to retheme existing utility classes
rather than editing every component.

**Pricing sections need a visible ladder.** Three tiers with three unrelated
feature lists tell a visitor nothing. Each tier above the first should open with
"Everything in <previous>, plus:" and the added items should be genuinely
bigger. If you cannot articulate what the extra money buys, the tier is wrong.

---

## 4. Wire it up

Read `references/forms-and-payments.md`. The essentials:

- Inquiries must reach a **real, verified inbox**. Static-page form services
  (Web3Forms and similar) work and cost nothing, but the destination is set in
  their dashboard, not in your code — so it cannot be confirmed by reading the
  repo, and it must be tested with a live submission.
- **Never put a secret API key in client code.** A mail or payments key in
  public JS lets anyone send as the client's domain or hit their account.
  Anything needing a secret goes behind a serverless function.
- A **checkout or booking modal beats scrolling to a form.** Someone who just
  chose a package should not have to find the contact section — carry the chosen
  package into the modal so the inquiry says what they picked.
- Give people who aren't ready a second door: a **"see the work first / book a
  short call"** action next to the buy action. Some fraction of buyers need
  reassurance, and without that door they leave.

---

## 5. Verify — the part that catches silent failures

Design review does not catch any of these. Run them every time.

### Email deliverability — non-negotiable

```bash
dig +short MX <the-domain-in-the-contact-address>
```

**No MX records means that address cannot receive mail, at all.** This is how the
ClientForge bug hid: `atouchofblessings.com` (plural) had no MX, the real domain
was `atouchofblessing.com` (singular), and every mailto click and reply-to
bounced. One letter. Check the domain in the contact address, the reply-to, and
anything the client told you — clients typo their own domain constantly.

Then **actually submit the form** and confirm arrival with the operator. A form
returning `success: true` only means the service accepted it, not that anyone
received it.

### Payload

Check what the page actually loads. On this stack the usual wins:

- Precompiled JSX, no in-browser compiler
- `react.production.min.js`, not `react.development.js` (~8× smaller)
- Subresource-integrity hashes on every CDN script

The ClientForge build went from **4.42 MB to 237 KB** on the script path from
these three alone.

### Verification traps — know what your tools cannot see

An automated browser pane will lie to you in specific ways, and misreading it
sends you fixing bugs that don't exist:

- **A hidden pane runs zero `requestAnimationFrame` frames.** Anything driven by
  rAF — scroll-scrub engines, most JS animation libraries — simply does not
  advance. Elements sit frozen at their initial state. Before concluding
  something is broken, check: `document.hidden` and count rAF frames over ~800 ms.
- **Screenshots often don't composite hardware video layers.** A blank capture
  where a video should be is usually a capture limitation. Confirm by drawing the
  video to a canvas and sampling pixel brightness.
- **Programmatic scroll then screenshot** frequently captures only the initial
  viewport. Verify scrolled state by reading the DOM, not by looking.

When a tool can't verify something, **say so plainly** rather than implying you
checked it. "The seam math is verified; the feel of it needs your eyes" is
useful. "Looks great!" about something you could not see is not.

Full detail in `references/verification.md`.

---

## 6. Ship

Read the deploy section of `references/buildless-stack.md`. Order matters:

1. Validate every file parses before committing
2. Confirm compiled output is in sync with sources
3. Commit with a message that explains *why*, not just what
4. Push, then **watch the deploy actually finish** — a build can fail after a
   successful push
5. Fetch the live URL with a cache-buster and confirm the new code is really
   being served
6. Re-run the email test **against production**

A failed deploy usually keeps the previous version live, which is a safe failure
mode — but it also means a green push and a live site can be different builds.
Always confirm against the live URL.

---

## Working style

**Decide, then say what you decided.** The operator is running a business, not
reviewing your options. Pick the tier, pick the palette, pick the copy — state
the choice and the reason in a sentence, and move. Reserve real questions for
money, branding, and anything irreversible.

**Spending money always asks first.** AI credits, ad spend, a paid plan, a domain
purchase. State the number, wait for a yes.

**Never invent proof.** No fake testimonials, no invented metrics, no client
logos the business doesn't have. Placeholder content must be obviously
placeholder. A page that lies converts once and costs the client their
reputation.

**Leave the client able to run it.** Where content will be swapped later — a
photo, a video, a price — make the slot obvious, degrade gracefully when it's
empty, and write down where the file goes. A missing video should render as a
tidy "coming soon" frame, never a broken player.

---

## Reference files

| File | Read it when |
|---|---|
| `references/scroll-world-hero.md` | Building a scroll-scrubbed hero, or generating any hero art/video with Higgsfield. Contains the seam discipline and credit math. |
| `references/buildless-stack.md` | Any build on this stack — conventions, global-scope collisions, precompiling, Vercel config. |
| `references/forms-and-payments.md` | Wiring inquiries, booking, or checkout. Includes the secret-key boundary and the Resend/Stripe upgrade path. |
| `references/verification.md` | Before shipping. The full checklist and the tool-limitation traps. |

`assets/` holds a vetted `scrub-engine.js` (scroll-scrub engine, no
dependencies), a `vercel.json` for static deploys, and a `package.json` build
setup for precompiling JSX.
