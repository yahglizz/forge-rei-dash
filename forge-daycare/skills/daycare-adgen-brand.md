---
skill: daycare-adgen-brand
role: Hard brand + image rules for the daycare Ad Generator (Nova / Ad Studio)
owner: human (Yahjair) — NOT a learned playbook; no learn() loop reads or rewrites it
loaded_by: daycare_ads_studio.ideas() via daycare_context.load_skill (mtime hot-reload)
sources: ~/Desktop/A Touch of Blessings — Brand Kit/brand/BRAND-KIT-FOR-AGENTS.md (v2.0, 2026-10-13),
  ATOB-BRAND-KIT.md §5 Voice + §8 Photography, forge-daycare/skills/enrollment-ad-agent.md (IMAGE rules),
  the higgsfield-prompt-writer skill (image formula)
---

# A Touch of Blessings — Ad Generator brand rules

Distilled from the binding brand kit. If this file and the brand kit disagree, the brand kit
wins — fix this file. Business facts (offers, expiry dates, hours, locations, licensing) come
ONLY from the DAYCARE CONTEXT brief; this file carries no offer.

## Hard rules (a concept that breaks one is wrong — do not output it)

1. **No children's faces. Ever.** (owner rule, enrollment-ad-agent.md). Never use stock photos of
   children (brand kit §8). An AI image must never pass as a real enrolled child. Show the
   ROOM, not the kids: warm tidy classrooms, reading corners, cubbies, art on the wall, small
   hands at work seen from behind or above, a parent's hand holding a small hand, backpacks
   at the door. No identifiable child, no child looking at the camera.
2. **Never invent a business fact.** No price, rate, seat count, opening, start date, STARS
   rating, staff name, review, testimonial, award or "#1" claim that is not in the context
   brief. Offers only as the brief words them, with its expiry. Unknown stays out of the ad.
3. **A Mother's Touch (1923 Cecil B. Moore) is a separate legal entity** — never market it as
   an A Touch of Blessings location, never "3 locations" in one ATOB ad.
4. **Licensing / subsidy claims exactly as the brief states them** — always
   "Child Care Works (CCIS)" on first mention. A wrong subsidy claim is a legal problem.
5. **Warm urgency, never pressure or guilt.** "Spots are filling fast" only when the brief or
   the live roster grounds open seats; otherwise lead with trust or the CCIS help.

## Voice (copy)

- Warm neighbor, lead with the child, specific not superlative ("6 AM – 6 PM", "ages
  6 weeks – 12 years"), plain English on money.
- Say *center* (never "facility"), *families* (never "clients"/"customers").
- Avoid: solutions, leverage, state-of-the-art, world-class, cheap, budget.
- Button language is verb-first ("Claim My Spot", "Book a Tour", "Call (215) 236-5439") —
  never "Learn More" / "Submit". Meta CTA enum: prefer SIGN_UP or CONTACT_US; never
  BOOK_TRAVEL; LEARN_MORE only when nothing else fits.

## Look (when an image carries an overlay)

- Colors: purple `#5B2C8E` structure, gold `#C9962B` as a ~10% accent (never a background,
  never gold text on white/cream), cream `#FFFAF2` / white base, charcoal `#1B1230` text.
- Type: Playfair Display (headline) + DM Sans (body) look. Warm color grade, lean cream and
  gold, avoid cold blue casts.
- Formats: 1:1 for feed, 9:16 for Stories/Reels (4:5 only if the engine offers it).

## IMAGE PROMPT CRAFT (Higgsfield)

One prompt = one job. Formula (under ~80 words, cinematography language, no filler):
`[subject + action], [setting], [shot type + lens], [lighting], [mood], [3–5 tags], [aspect]`

- **Subject:** the room or an object story (rule 1). Concrete: "low wooden shelves of picture
  books, a cushioned reading nook, crayon drawings pinned on a cork board".
- **Setting:** a real-feeling North Philadelphia childcare classroom — clean, uncluttered
  (a tidy room is itself a trust signal).
- **Shot + lens:** eye-level wide 24–35mm for rooms; 50–85mm shallow depth of field for
  hands/objects.
- **Light:** soft natural window light, warm golden afternoon; never cold blue.
- **Mood:** safe, calm, loved, "a second home".
- **Negative space:** leave a clean area (top third or one side) for the headline overlay.
- **Text in the image:** only with a text-capable model (gpt_image_2 renders text well);
  then give the EXACT overlay words in quotes, ≤6 words headline + ≤8 words subtext, and the
  overlay copy obeys rule 2. Otherwise say "no text in image".
- **Tags:** photorealistic, warm tones, natural light, shallow depth of field, 4K.
- **Always end** with the aspect ratio of the chosen format (`1:1` or `9:16 vertical`).
