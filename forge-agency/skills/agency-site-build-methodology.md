# Site-build methodology (Dyson)

The distilled floor for how ClientForge scopes and builds a client site. It came
out of a real build and encodes the failures that cost money there. Apply it; the
creed still outranks it.

## Scope from what a customer is worth, not from what looks impressive

Before proposing anything, establish: what one customer is worth, where leads
come from today, and what the ONE action a visitor should take is. A site whose
build price dwarfs the client's job value is a bad recommendation no matter how
good it looks — a $2,500 build for a business doing $150 jobs has to survive 17
customers before it breaks even.

One primary action per page. A visitor deciding between four things does none of
them. Match the action to how the business actually closes: trades and services
close on the phone (`tel:` links, tap-to-call, not a form), considered purchases
close on a booked call, products close in a cart.

Price in a visible ladder. Each tier opens with "Everything in <previous>, plus:"
so the extra money maps to named added scope — otherwise the tiers read as three
unrelated lists and the client cannot see what they're buying.

For anything recurring (ads, management), quote the MANAGEMENT FEE and say on the
card that the client pays the platform directly for spend. Bundling spend into
one number makes margin invisible and the invoice a fight.

## Never invent proof

No testimonial, review count, jobs-completed figure, years-in-business, or result
metric unless the client supplied it. Fabricated proof on a live business site is
deceptive advertising and the CLIENT carries the risk. It is also invisible in a
design review because it looks finished.

Leave the slot visibly empty and labelled as awaiting the real thing. An empty
slot is a task; an invented one is a liability. The same applies to prices and
phone numbers — mark placeholders as placeholders in the handoff notes.

## The inquiry path is the deliverable

A website that looks perfect and drops leads has failed at the only job it has.

- **Check the contact domain can receive mail before anything else** —
  `dig +short MX <domain>`. No MX means every inquiry and every reply bounces
  silently. This is not hypothetical: ClientForge published a dead domain
  (`atouchofblessings.com`, plural, no MX) for months.
- A form endpoint returning HTTP 200 does NOT mean an email arrived. Where the
  mail lands is usually a dashboard setting, not code — confirm it, and record
  where it goes, because it cannot be read back from the repo.
- Test the real inquiry path on the live site after deploy, not just locally.
- Never put a payment or email API secret in client-side code. If it needs a
  secret it needs a server function, and the key belongs in an env var.

## Ship it light

Static React over a CDN with Tailwind is fine and needs no bundler, but compile
JSX ahead of time and use production React — shipping an in-browser compiler
costs every visitor megabytes for nothing. On the ClientForge build that one
change cut the script payload 94% (4.4 MB to 237 KB).

If build output is committed rather than built on deploy, a stale-output guard
matters more than it sounds: editing a source file and shipping the old compiled
copy is silent and total.

## Cinematic hero art: only when it earns its place

AI-generated scroll-flight heroes are expensive (roughly 200+ credits for a full
set) and slow to load. They suit a client selling an experience or a premium
brand. They are the wrong call for a local service business that needs a phone
number above the fold — recommend a static hero and say plainly that you are
saving the spend. Any credit spend is the operator's approval, with the cost
stated first.

## Report honestly

Say what was verified and how, and name what was not. "Should work" is not a
result. If a check could not run, that belongs in the handoff rather than
implied success — the operator is going to put their name on this in front of a
paying client.
