---
name: lead-followup-skill
version: 1.0.0
description: >
  Full GHL lead follow-up audit and send process for FORGE REI OS.
  Classifies all conversations, skips DNC/rejections/double-texts,
  and sends personal Elizabeth follow-ups to un-replied or interested leads.
triggers:
  - "follow up with leads"
  - "audit my messages"
  - "send follow ups"
  - "check who didn't reply"
  - "maximize leads"
  - "run lead follow-up"
  - "text the list"
  - "elizabeth follow up"
  - "send follow ups to leads"
  - "check who didn't reply and text them"
  - "audit my messages and follow up"
agents:
  - marcus
  - scout
tags:
  - ghl
  - wholesale
  - sms
  - follow-up
  - leads
---

# FORGE REI OS — Lead Follow-Up Skill

## Purpose

Run a complete audit of all GHL conversations and send personal SMS follow-ups
to leads who have not replied or who showed genuine interest. Respect daily SMS
limits, DNC rules, and the "Elizabeth" identity at all times.

---

## Identity Rules (CRITICAL — NEVER BREAK THESE)

- **Sender name is always "elizabeth"** — lowercase, no last name, no "Yahjair"
- Casual, lowercase, personal tone — no corporate language, no templates that
  sound templated
- Max 2 sentences per follow-up message
- Never start a message with "I" (CAN-SPAM best practice)
- Never use exclamation points in cold SMS

---

## GHL API Reference

| Item | Value |
|------|-------|
| Base URL | `https://services.leadconnectorhq.com` |
| Auth header | `Authorization: Bearer {GHL_API_KEY}` |
| API-Version header | `2021-07-28` |
| Location ID | `8GuqpADet7ivY7wXWTpV` |
| Creds file | `/Users/yg4st/forge rei dash/marcus-wholesale-agent/config/ghl.env` |
| Daily SMS hard cap | **1,500 / day** |

### Key Endpoints

```
# List conversations (paginate with skip)
GET /conversations/search
  ?locationId=8GuqpADet7ivY7wXWTpV
  &limit=100
  &skip={offset}

# Send SMS
POST /conversations/messages
  Body: { "type": "SMS", "contactId": "...", "conversationId": "...", "message": "..." }

# Tag a contact
POST /contacts/{contactId}/tags
  Body: { "tags": ["dnc"] }

# Get contact detail (for tag check)
GET /contacts/{contactId}
```

---

## Step-by-Step Process

### 1. Load creds

```bash
source "/Users/yg4st/forge rei dash/marcus-wholesale-agent/config/ghl.env"
# GHL_API_KEY is now set
```

### 2. Check today's sent count

Before sending anything, count how many SMS have gone out today. Stop sending
if `sent_today >= 1,500`.

### 3. Pull all conversations

Paginate through `GET /conversations/search` with `limit=100` and
`skip=0, 100, 200, ...` until the returned list is empty.

Current total: ~7,350 conversations (re-verify on each run — number grows).

### 4. Classify each conversation

For every conversation evaluate in this order (first match wins):

#### HARD SKIP — DNC

Mark as DNC and **do not send** if ANY of these are true:

- `lastMessageBody` contains (case-insensitive):
  `STOP`, `remove`, `wrong number`, `unsubscribe`, `take me off`
- Contact already has tag `dnc`

**Action:** `POST /contacts/{id}/tags` with `{ "tags": ["dnc"] }` if not already tagged.

#### SKIP — Rejection / Hostility

Do not send if the last **inbound** message contains any of:

```
no, not interested, not selling, already sold, listed with agent,
leave me alone, wrong number, stop, remove me, not looking,
not for sale, take me off, unsubscribe
```

#### SKIP — Texted Today

Do not send if any outbound message was sent today (same calendar date UTC-5).
Never double-text the same day.

#### SEND — Hot Lead (Inbound with Interest Signals)

Inbound message contains any of:
`yes, interested, how much, price, open to, when, call me, sure, okay,
sounds good, what's the offer, what can you offer, let's talk, maybe,
what would you pay`

Use a **custom message** (see Hot Lead Messages section below).

#### SEND — No Reply

Outbound-only conversation, homeowner never responded. Use the **default
follow-up message**.

---

## Message Templates

### Default Follow-Up (no reply leads)

```
hey {firstName} this elizabeth, just personally checking back in. still open to talking about the property? no rush
```

### Hot Lead Custom Messages

**Asked for offer / wants a number:**
```
hey {firstName} this elizabeth, ready to get you that offer. can we hop on a quick 5 min call so i can give you the most accurate number? just let me know a good time
```

**Said yes / interested:**
```
hey {firstName} glad you reached back out, still very interested in your property. can we hop on a quick call so i can put together a real offer for you?
```

**Contract stage (DocuSign already sent):**
```
hey {firstName} just making sure the docusign hit your email okay. let me know if you have any questions before you sign
```

**Waiting on photos:**
```
hey {firstName} no rush on those photos, whenever you ready just send them over and ill get you our best number
```

**Firm on price, hasn't replied:**
```
hey {firstName} this elizabeth, i dont wanna lose this deal. you open to a quick call so we can figure it out?
```

**FSBO threat (said they'll list it themselves):**
```
hey {firstName} before you list it yourself real quick let me show you what you actually net after commissions vs selling to us. might be worth a 5 min look
```

---

## Send Logic

```python
sent_today = get_sms_sent_today()   # count from GHL activity log

for convo in all_conversations:
    if sent_today >= 1500:
        print("Daily cap reached — stopping")
        break

    classification = classify(convo)

    if classification == "DNC":
        tag_contact_dnc(convo.contactId)
        continue

    if classification in ("SKIP_REJECTION", "SKIP_DOUBLE_TEXT"):
        continue

    if classification in ("SEND_HOT", "SEND_NO_REPLY"):
        message = build_message(convo)
        send_sms(convo.contactId, convo.id, message)
        sent_today += 1
        log(convo.contactId, message)
```

---

## Batch Run Checklist

Before starting:
- [ ] Creds loaded from `ghl.env`
- [ ] Today's sent count checked
- [ ] Pagination offset reset to 0
- [ ] DNC tag list refreshed

During run:
- [ ] Log every send: `contactId | firstName | phone | message | timestamp`
- [ ] Log every skip with reason
- [ ] Stop at 1,500 sends

After run:
- [ ] Report: sent / skipped-dnc / skipped-rejection / skipped-double-text / cap-reached
- [ ] Flag hot leads (interest signals) for Marcus review within 1 hour
- [ ] Any inbound replies received during the batch go to Marcus immediately

---

## Marcus Coordinator Rules

When Marcus runs this skill:
1. Pull and classify first — never send before classification pass is complete
2. Flag ambiguous cases (neutral inbound, partial interest signals) for human
   review before sending
3. Hot leads that replied positively within the last 24 h get escalated to
   top of list — send their custom message first before default follow-ups
4. After run, produce a summary report in this format:

```
FOLLOW-UP RUN COMPLETE
Date: {date}
Total convos scanned: {n}
Sent: {sent}
Skipped (DNC): {dnc}
Skipped (rejection): {rejection}
Skipped (double-text): {double}
Hot leads flagged: {hot}
Daily cap hit: yes/no
```

---

## Scout Rules

When Scout runs this skill as part of an automated sweep:
- Run classification-only pass first, write results to a temp log
- Do not send SMS without Marcus or operator confirmation unless explicitly
  authorized with "auto-send approved"
- Always surface DNC candidates to operator before tagging

---

## Error Handling

| Error | Action |
|-------|--------|
| 429 Too Many Requests | Back off 60 s, resume |
| 401 Unauthorized | Reload creds from `ghl.env`, retry once |
| Contact not found | Skip, log warning |
| SMS delivery failed | Log failed number, skip, do not retry same day |
| Daily cap hit mid-batch | Stop immediately, log offset, resume next day from that offset |

---

## Related Skills

- `wholesale-seller-texter` — initial outbound blast (first contact)
- `marcus-seller-reply` — classify and respond to inbound replies
- `marcus-nurture-followup` — long-term nurture sequence for cold leads
- `marcus-lead-agent` — full lead lifecycle orchestration
