"""Self-check for daycare_replies: the GHL-automation yield rules, draft flags, and the
approve path's live re-check. No network, no Claude. Run: python3 test_daycare_replies.py"""
import os
import tempfile
from pathlib import Path
from unittest import mock

import daycare_replies as dr

NOW = 1_790_000_000.0          # a fixed epoch; hours checks are stubbed where needed
MIN = 60


def msg(i, direction, body, ago, source="", mtype="TYPE_SMS"):
    return {"id": f"m{i}", "direction": direction, "body": body, "source": source,
            "messageType": mtype, "dateAdded": int((NOW - ago) * 1000)}


def g(msgs, contact=None):
    return dr.gate(contact or {}, msgs, NOW)


def test_channel_dnd():
    """A carrier rejection (Twilio 30006) sets only dndSettings.SMS. GHL then refuses the send,
    so the gate must see it too or the owner gets "result unknown" instead of the reason."""
    blocked = {"dnd": None, "dndSettings": {"SMS": {"status": "active", "message": "TWILIO_ERROR_CODE: 30006"}}}
    assert dr._dnd(blocked) is True
    assert dr._dnd({"dnd": True}) is True
    assert dr._dnd({"dnd": False, "dndSettings": {"SMS": {"status": "inactive"}, "Call": {"status": "active"}}}) is False
    assert dr._dnd({}) is False
    assert dr._dnd({"dndSettings": {"SMS": {"status": "permanent", "message": "STOP_KEYWORD"}}}) is True
    assert dr._dnd({"dndSettings": {"sms": {"status": "active"}}}) is True
    assert dr._dnd({"dndSettings": {"SMS": "active"}}) is True
    assert dr._dnd({"dndSettings": "garbage"}) is False
    parent = [msg(1, "inbound", "hi do you have infant openings?", 30 * MIN)]
    assert g(parent, blocked) == (False, "dnd")


def test_gate():
    parent = [msg(1, "inbound", "hi do you have infant openings?", 30 * MIN)]
    assert g(parent) == (True, None)
    # a person or workflow already answered
    assert g(parent + [msg(2, "outbound", "hey yes let me check", 10 * MIN)]) == (False, "answered")
    # grace window: GHL stop-on-response / live staff go first
    assert g([msg(1, "inbound", "hello?", 60)]) == (False, "grace")          # <90 s: wait
    assert g([msg(1, "inbound", "hello?", 2 * MIN)]) == (True, None)         # >90 s: answer — inside 5 min
    # STOP/HELP belong to GHL keyword auto-replies; opt-out is forever
    assert g([msg(1, "inbound", "HELP", 30 * MIN)]) == (False, "keyword")
    assert g([msg(1, "inbound", "STOP", 30 * MIN)])[0] is False
    assert g([msg(1, "inbound", "stop texting me", 60 * MIN),
              msg(2, "inbound", "actually what are your hours", 30 * MIN)]) == (False, "opted_out")
    # not SMS -> Lead Desk handles it
    assert g([msg(1, "inbound", "hi", 30 * MIN, mtype="TYPE_LIVE_CHAT")]) == (False, "not_sms")
    # speed-to-lead owns the first touch
    lead = {"tags": ["form-type-new-inquiry", "speed-to-lead-trigger"],
            "dateAdded": int((NOW - 4 * MIN) * 1000)}
    assert g([msg(1, "inbound", "is this the daycare?", 2 * MIN)], lead) == (False, "stl_pending")
    stale_lead = dict(lead, dateAdded=int((NOW - 9 * MIN) * 1000))            # workflow never fired
    assert g([msg(1, "inbound", "is this the daycare?", 2 * MIN)], stale_lead) == (True, None)
    queued = {"tags": ["form-type-new-inquiry", "speed-to-lead-queued"]}
    assert g([msg(1, "inbound", "hi", 30 * MIN)], queued) == (False, "stl_queued")
    # workflow sent the first touch, parent replied -> ours
    assert g([msg(1, "outbound", "Hi Tasha, this is management over at A Touch of Blessings",
                  60 * MIN, source="workflow"),
              msg(2, "inbound", "yes can we tour friday", 30 * MIN)], lead) == (True, None)
    assert g(parent, {"dnd": True}) == (False, "dnd")
    assert g([msg(1, "inbound", "hi", 9 * 86400)]) == (False, "stale")
    assert g([]) == (False, "no_thread")


def test_flags():
    assert dr.flags("call us at (215) 236-5439 or 215-787-0100") == []
    assert dr.flags("ELRC is 1-888-461-KIDS") == []
    assert dr.flags("call 267-457-0519") == ["unverified_phone"]
    assert dr.flags("its $250 a week") == ["money"]
    assert "long" in dr.flags("x" * 500)


class FakeClient:
    configured = True
    location_id = "loc"

    def __init__(self, convs, msgs):
        self.convs, self.msgs, self.sent = convs, msgs, []

    def get(self, ep, params=None):
        if ep == "/conversations/search":
            return {"conversations": self.convs}
        if ep.endswith("/messages"):
            return {"messages": {"messages": self.msgs}}
        if ep.startswith("/contacts/"):
            return {"contact": {"id": "c1", "tags": ["loc-921-n-18th", "daycare family"]}}
        return {}

    def post(self, ep, body):
        self.sent.append(body)
        return {"messageId": "sent1"}


def test_sweep_and_approve():
    dr.STATE = Path(tempfile.mkdtemp()) / "replies.json"
    conv = {"id": "v1", "contactId": "c1", "lastMessageDirection": "inbound",
            "lastMessageDate": int((NOW - 30 * MIN) * 1000)}
    parent = [msg(1, "inbound", "she's sick today she won't be in", 30 * MIN)]
    fake = lambda contact, ev, now: {"action": "draft", "category": "logistics",
                                     "draft": "ok thank you for letting us know", "why": "",
                                     "unknowns": [], "flags": [], "model": "test"}
    cl = FakeClient([conv], parent)
    r = dr.run_once(cl, now=NOW, drafter=fake)
    assert r["drafted"] == 1, r
    assert dr.view()["pending"][0]["center"] == "921 N 18th St"
    # same inbound -> no second Claude call
    assert dr.run_once(cl, now=NOW, drafter=fake)["drafted"] == 0
    # approve: staff answered in GHL meanwhile -> refuse, retire, send nothing
    dr.daycare_leads.in_hours = lambda now: True
    cl.msgs = parent + [msg(2, "outbound", "feel better!", 5 * MIN)]
    out = dr.approve(cl, "c1", now=NOW)
    assert not out["ok"] and "already replied" in out["error"] and cl.sent == []
    # fresh draft, clean thread -> exactly one send
    conv["lastMessageDate"] = int((NOW - 10 * MIN) * 1000)
    cl.msgs = parent + [msg(2, "outbound", "feel better!", 20 * MIN),
                        msg(3, "inbound", "thank you, back tomorrow", 10 * MIN)]
    assert dr.run_once(cl, now=NOW, drafter=fake)["drafted"] == 1
    assert dr.approve(cl, "c1", now=NOW)["ok"] and len(cl.sent) == 1
    assert dr.approve(cl, "c1", now=NOW)["ok"] is False          # no double send
    # quiet hours block even the owner
    dr.daycare_leads.in_hours = lambda now: False
    conv["lastMessageDate"] = int((NOW - 5 * MIN) * 1000)
    cl.msgs = parent + [msg(4, "inbound", "one more question", 5 * MIN)]
    dr.run_once(cl, now=NOW, drafter=fake)
    assert "8am" in dr.approve(cl, "c1", now=NOW)["error"]


def test_auto_send():
    # pure eligibility: a clean enrollment-lead answer only
    ok = {"action": "draft", "category": "tour", "draft": "we'd love to show you around", "flags": []}
    assert dr.auto_eligible(ok, "lead")
    assert not dr.auto_eligible(ok, "family")                                  # enrolled family: owner
    assert not dr.auto_eligible(dict(ok, flags=["money"]), "lead")             # flagged: owner
    assert not dr.auto_eligible(dict(ok, category="billing"), "lead")          # off-limits topic
    assert not dr.auto_eligible(dict(ok, action="escalate"), "lead")
    assert not dr.auto_eligible(dict(ok, draft=" "), "lead")
    for bad in ("safety", "custody", "medical", "complaint", "billing", "hiring", "other", "logistics"):
        assert bad not in dr.AUTO_SAFE_CATEGORIES, bad
    # end to end: ON sends once inside hours, respects cap + per-contact limit; OFF sends nothing
    dr.STATE = Path(tempfile.mkdtemp()) / "replies.json"
    dr.daycare_leads.in_hours = lambda now: True
    dr._contact = lambda client, cid: {"id": cid, "tags": ["form-type-new-inquiry"]}
    conv = {"id": "v1", "contactId": "c1", "lastMessageDirection": "inbound",
            "lastMessageDate": int((NOW - 3 * MIN) * 1000)}
    parent = [msg(1, "inbound", "do you take ccis?", 3 * MIN)]
    fake = lambda contact, ev, now: {"action": "draft", "category": "subsidy", "flags": [], "why": "",
                                     "draft": "yes we do — how old is your little one?",
                                     "unknowns": [], "model": "t"}
    cl = FakeClient([conv], parent)
    dr.AUTO = False
    r = dr.run_once(cl, now=NOW, drafter=fake)
    assert r["drafted"] == 1 and cl.sent == [] and r["auto"]["sent"] == 0      # default: draft only
    dr.AUTO = True
    assert dr.auto_send(cl, NOW)["sent"] == 1 and len(cl.sent) == 1
    assert dr.view(NOW)["auto"]["sentToday"] == 1
    assert dr.auto_send(cl, NOW)["sent"] == 0 and len(cl.sent) == 1            # no double send
    dr.AUTO = False


def test_quote_only_on_owner_tap():
    """Owner rule 2026-11-12: a rate quote waits for his tap. Never auto-sent, rates come from
    the sheet by the child's age, and any other dollar figure is flagged."""
    q = lambda label, brand, m: dr.quote_basis(label, brand, m)
    t, a = q("921 N 18th St", "A Touch of Blessings", 8)
    assert a == {135.0, 195.0} and "Infants" in t
    assert q("921", "A Touch of Blessings", 14)[1] == {125.0, 180.0}
    assert q("921", "A Touch of Blessings", 24)[1] == {115.0, 165.0}        # 2nd birthday = older toddler
    assert q("921", "A Touch of Blessings", 36)[1] == {100.0, 145.0}
    assert q("2318", "A Touch of Blessings", 72)[1] == {85.0, 120.0}
    assert q("2318", "A Touch of Blessings", 120)[1] == {75.0, 110.0}
    for no in (q("", "", 8), q("1923", "A Mother's Touch", 8), q("921", "A Touch of Blessings", None),
               q("921", "A Touch of Blessings", 1), q("921", "A Touch of Blessings", 160)):
        assert no[1] == set() and no[0].startswith("NO NUMBER"), no
    # sheet-driven draft: two stated rates are legal, anything else is flagged, never auto
    import review_agent
    kid = {"id": "c1", "tags": ["loc-921-n-18th", "form-type-new-inquiry"],
           "customFields": [{"id": dr.daycare_ghl.CF_CHILD_DOB, "value": "2026-03-01"}]}
    ev = [{"id": "m1", "dir": "inbound", "body": "how much for infant care?", "t": NOW, "auto": False}]
    def draft(contact, body):
        orig = review_agent._claude
        review_agent._claude = lambda *a, **k: '{"action":"draft","category":"pricing","draft":"%s"}' % body
        try:
            return dr.draft_reply(contact, ev, NOW + 86400 * 400, key="k")
        finally:
            review_agent._claude = orig
    kid["customFields"][0]["value"] = dr.datetime.fromtimestamp(NOW + 86400 * 400 - 86400 * 30 * 8, dr.daycare_leads.ET).strftime("%Y-%m-%d")
    good = draft(kid, "Infants are $135/week part-time or $195/week full-time.")
    assert "money" in good["flags"] and "money_unverified" not in good["flags"] and good["quoteBasis"]
    assert not dr.auto_eligible(good, "lead")                                   # never by itself
    bad = draft(kid, "Infants are $250/week.")
    assert "money_unverified" in bad["flags"]
    amt = draft(dict(kid, tags=["loc-1923-cecil-b-moore"]), "Infants are $135/week.")
    assert "money_unverified" in amt["flags"] and amt["quoteBasis"] == ""
    assert "pricing" not in dr.AUTO_SAFE_CATEGORIES
    assert not dr.auto_eligible({"action": "draft", "category": "pricing", "draft": "call us", "flags": []}, "lead")
    # auto-send ON still sends nothing for a priced draft; the owner gets a "waiting for your tap" ping
    dr.STATE = Path(tempfile.mkdtemp()) / "replies.json"
    dr.daycare_leads.in_hours = lambda now: True
    dr._contact = lambda client, cid: {"id": cid, "tags": ["form-type-new-inquiry"]}
    conv = {"id": "v9", "contactId": "c9", "lastMessageDirection": "inbound",
            "lastMessageDate": int((NOW - 3 * MIN) * 1000)}
    cl = FakeClient([conv], [msg(1, "inbound", "how much is infant care?", 3 * MIN)])
    pings = []
    import telegram_io
    telegram_io.send_biz = lambda biz, text, **kw: pings.append(text) or {"ok": True}
    fake = lambda contact, ev, now: {"action": "draft", "category": "pricing", "flags": ["money"], "why": "",
                                     "draft": "Infants are $135/week part-time or $195/week full-time.",
                                     "unknowns": [], "quoteBasis": "Infants...", "model": "t"}
    dr.AUTO = True
    try:
        r = dr.run_once(cl, now=NOW, drafter=fake)
        assert r["drafted"] == 1 and cl.sent == [] and r["auto"]["sent"] == 0
    finally:
        dr.AUTO = False
    assert pings and "Quote ready" in pings[0] and "NOT sent" in pings[0] and "$135" in pings[0]


def test_send_quote_button_end_to_end():
    """Parent asks price -> draft + owner card with ONE Send quote button -> nothing sent until the
    tap -> tap sends exactly the text on the card, once. Stale / unbacked / off-hours taps send nothing."""
    import telegram_io, slack_io
    cid = "Abc123XyZ789dEf456gH"                      # a realistic 20-char GHL contact id
    dr.STATE = Path(tempfile.mkdtemp()) / "replies.json"
    dr.daycare_leads.in_hours = lambda now: True
    dr._contact = lambda client, c: {"id": c, "tags": ["loc-921-n-18th", "form-type-new-inquiry"]}
    conv = {"id": "v1", "contactId": cid, "lastMessageDirection": "inbound",
            "lastMessageDate": int((NOW - 3 * MIN) * 1000)}
    parent = [msg(1, "inbound", "how much is infant care?", 3 * MIN)]
    cl = FakeClient([conv], parent)
    cards = []
    telegram_io.send_biz = lambda biz, text, **kw: cards.append((text, kw)) or {"ok": True}
    text = "Infants are $135/week part-time or $195/week full-time."
    mk = lambda body, fl=None: (lambda contact, ev, now: {
        "action": "draft", "category": "pricing", "flags": fl if fl is not None else ["money"], "why": "",
        "draft": body, "unknowns": [], "quoteBasis": "Infants (6 weeks-12 months): ...", "model": "t"})
    dr.AUTO = True                                   # even with auto-send ON, only the tap sends
    try:
        assert dr.run_once(cl, now=NOW, drafter=mk(text))["drafted"] == 1
    finally:
        dr.AUTO = False
    assert cl.sent == [], "nothing goes out before the tap"
    body, kw = cards[0]
    btn = kw["buttons"][0][0]
    assert btn["text"] == "💲 Send quote" and len(kw["buttons"]) == 1 and len(kw["buttons"][0]) == 1
    cb = btn["callback_data"]
    assert cb.startswith("quotesend:" + cid + ":") and len(cb.encode()) <= 64         # Slack + Telegram limit
    assert slack_io.render_blocks(body, kw["buttons"], "c1")[-1]["elements"][0]["value"] == cb   # survives in Slack
    arg = cb.split(":", 1)[1]
    # a tap on a card whose draft was since replaced sends nothing
    assert "changed" in dr.send_quote_tap(cl, cid + ":deadbeef")["error"] and cl.sent == []
    # outside 8am-9pm ET: nothing, draft stays pending
    dr.daycare_leads.in_hours = lambda now: False
    assert "8am" in dr.send_quote_tap(cl, arg, now=NOW)["error"] and cl.sent == []
    dr.daycare_leads.in_hours = lambda now: True
    # the tap: exactly one SMS, exactly the card's text
    r = dr.send_quote_tap(cl, arg, now=NOW)
    assert r["ok"] and r["message"] == "Quote sent." and len(cl.sent) == 1
    assert text in str(cl.sent[0]) and dr.view(NOW)["auto"]["sentToday"] == 0       # owner tap, not auto
    assert dr.send_quote_tap(cl, arg, now=NOW)["ok"] is False and len(cl.sent) == 1  # double tap = no resend
    # a quote with a figure the sheet did not give: card has NO button, the tap path refuses anyway
    cards.clear()
    conv["lastMessageDate"] = int((NOW - 2 * MIN) * 1000)
    cl.msgs = parent + [msg(2, "outbound", "sent", 10 * MIN), msg(3, "inbound", "and toddlers?", 2 * MIN)]
    bad = mk("Infants are $250/week.", ["money", "money_unverified"])
    assert dr.run_once(cl, now=NOW, drafter=bad)["drafted"] == 1
    assert "buttons" not in cards[0][1] or not cards[0][1]["buttons"]
    assert "not on the rate sheet" in cards[0][0]
    assert "not backed" in dr.send_quote_tap(cl, cid + ":" + dr.quote_token("Infants are $250/week."))["error"]
    assert len(cl.sent) == 1
    # wiring: the connector registers the tap and Telegram/Slack know its audit label
    src = Path(__file__).with_name("connector.py").read_text(encoding="utf-8")
    assert '"quotesend": lambda arg' in src and "daycare_replies.send_quote_tap(DAYCARE_GHL, arg)" in src
    assert telegram_io._result_text("quotesend", {"ok": True}) == "💲 Quote sent"
    assert any(k == "quotesend" for k, _, _ in telegram_io._TAP_AGENT)


def test_pricing_card_layout_and_retry():
    """One organized card for every price question: same sections, in order, and a button only when
    the figures are on the sheet. A transient send failure keeps the draft tappable."""
    esc = lambda x: str(x or "")
    base = {"contactId": "c1", "parentName": "Tasha", "center": "921 N 18th St", "inboundText": "how much is infant?",
            "childAge": "8 months", "quoteGroup": "Infants (6 weeks-12 months)",
            "quoteRates": "part-time $135 · full-time $195 per week (private pay)", "flags": ["money"],
            "draft": "Infants are $135/week part-time or $195/week full-time.", "unknowns": ["open infant seats"]}
    text, btn = dr.pricing_card(base, esc)
    order = [text.index(k) for k in ("Quote ready", "Parent:", "Child:", "Asked:", "Rates:", "Also to confirm:",
                                     "Draft (NOT sent):", "Next:")]
    assert order == sorted(order) and btn[0][0]["text"] == "💲 Send quote"
    assert btn[0][0]["callback_data"] == f"quotesend:c1:{dr.quote_token(base['draft'])}"
    text, btn = dr.pricing_card(dict(base, flags=["money", "money_unverified"], quoteRates=""), esc)
    assert btn is None and "needs a fix" in text and "not on the rate sheet" in text
    text, btn = dr.pricing_card(dict(base, draft="how old is your little one?", flags=[], quoteRates="", quoteGroup="",
                                     childAge="not on file", noNumber="child's age unknown. Ask how old the child is."), esc)
    assert btn is None and "Price question: no number yet" in text and "Why no number:" in text and "date of birth" in text
    # transient failures keep the card tappable; a final refusal does not
    dr.STATE = Path(tempfile.mkdtemp()) / "replies.json"
    dr.daycare_leads.in_hours = lambda now: True
    dr._contact = lambda client, c: {"id": c, "tags": ["loc-921-n-18th", "form-type-new-inquiry"]}
    conv = {"id": "v1", "contactId": "c1", "lastMessageDirection": "inbound", "lastMessageDate": int((NOW - 3 * MIN) * 1000)}
    cl = FakeClient([conv], [msg(1, "inbound", "how much is infant care?", 3 * MIN)])
    import telegram_io
    telegram_io.send_biz = lambda biz, text, **kw: {"ok": True}
    q = {"action": "draft", "category": "pricing", "flags": ["money"], "why": "", "unknowns": [], "model": "t",
         "draft": base["draft"], "quoteBasis": "Infants..."}
    dr.run_once(cl, now=NOW, drafter=lambda c, e, n: dict(q))
    arg = "c1:" + dr.quote_token(base["draft"])
    dr.daycare_leads.in_hours = lambda now: False
    r = dr.send_quote_tap(cl, arg, now=NOW)
    assert not r["ok"] and r["retry"] is True and cl.sent == []                 # 9:30pm: keep the button
    dr.daycare_leads.in_hours = lambda now: True
    real = dr.daycare_ghl.send_sms
    dr.daycare_ghl.send_sms = lambda *a, **k: {"ok": False, "error": "GHL 500"}
    try:
        r = dr.send_quote_tap(cl, arg, now=NOW)
        assert not r["ok"] and r["retry"] is True                                # GHL hiccup: keep the button
    finally:
        dr.daycare_ghl.send_sms = real
    r = dr.send_quote_tap(cl, arg, now=NOW)
    assert r["ok"] and len(cl.sent) == 1 and "retry" not in r                   # second tap goes out once
    r = dr.send_quote_tap(cl, arg, now=NOW)
    assert not r["ok"] and not r.get("retry") and len(cl.sent) == 1             # sent: final, no resend


def test_age_from_website_form():
    """Website inquiries carry the age as text in childAge ("2 Years", "8 Months", "6 Weeks"), not a
    date of birth. The quote must use it (live miss 2026-11-12: a lead with "2 Years" got no number)."""
    age = lambda v, dob=None: {"id": "c", "tags": ["loc-2318-cecil-b-moore"], "customFields":
                               [{"id": dr.CF_CHILD_AGE, "value": v}] + ([{"id": dr.daycare_ghl.CF_CHILD_DOB, "value": dob}] if dob else [])}
    assert dr._child_age(age("2 Years"), NOW) == (24, "form", False)
    assert dr._child_age(age("8 Months"), NOW) == (8, "form", False)
    assert dr._child_age(age("2 Years (+1 sibling)"), NOW) == (24, "form", True)
    assert dr._child_age(age("1-2 Years"), NOW) == (None, "", False)            # legacy range: no guess
    assert dr._child_age(age(""), NOW) == (None, "", False)
    m, src, _ = dr._child_age(age("6 Weeks"), NOW)
    assert src == "form" and dr.rate_row(m)[1].startswith("Infants")
    assert dr.rate_row(dr._child_age(age("5 Weeks"), NOW)[0]) is None           # under 6 weeks: no rate
    assert dr.rate_row(1) is None and dr.rate_row(2) is not None                 # DOB whole months stay safe
    assert dr.rate_row(24)[1].startswith("Older Toddlers") and dr.rate_row(12)[1].startswith("Young Toddlers")
    born = dr.datetime.fromtimestamp(NOW - 86400 * 400, dr.daycare_leads.ET).strftime("%Y-%m-%d")
    assert dr._child_age(age("2 Years", dob=born), NOW)[1] == "dob"             # a real DOB wins
    t, a = dr.quote_basis("2318 Cecil B Moore", "A Touch of Blessings", 24, siblings=True)
    assert a == {115.0, 165.0} and "sibling" in t
    assert dr.age_text(24) == "2 years" and dr.age_text(8) == "8 months" and dr.age_text(6 / 4.345) == "6 weeks"


def test_owner_handoff():
    sent = []
    import telegram_io
    telegram_io.send_biz = lambda biz, text, **kw: sent.append((biz, text, kw)) or {"ok": True}
    base = {"contactId": "c9", "inboundId": "m1", "parentName": "Tasha", "center": "921 N 18th St",
            "inboundText": "do you have a <bus> for pickup?", "draft": "let me confirm and get right back to you"}
    assert dr.notify_owner(dict(base, action="draft", unknowns=["school-bus pickup"]))
    assert sent[0][0] == "daycare" and "&lt;bus&gt;" in sent[0][1] and "school-bus pickup" in sent[0][1]
    assert sent[0][2]["dedupe_key"] == "dcreply:c9:m1"
    assert dr.notify_owner(dict(base, action="escalate", unknowns=[]))         # safety topic: always
    assert "NOW" in sent[1][1]
    assert not dr.notify_owner(dict(base, action="draft", unknowns=[]))        # fully answered: no ping
    assert not dr.notify_owner(dict(base, action="no_reply", unknowns=["x"]))


def test_ai_down_stops_sweep():
    dr.STATE = Path(tempfile.mkdtemp()) / "replies.json"
    convs = [{"id": f"v{i}", "contactId": f"c{i}", "lastMessageDirection": "inbound",
              "lastMessageDate": int((NOW - 30 * MIN) * 1000)} for i in range(3)]
    calls = []

    def broke(contact, ev, now):
        calls.append(1)
        raise RuntimeError("Anthropic API error (400): Your credit balance is too low")
    r = dr.run_once(FakeClient(convs, [msg(1, "inbound", "hi are you open", 30 * MIN)]),
                    now=NOW, drafter=broke)
    assert len(calls) == 1 and "credit" in r["error"] and "credit" in dr.view()["error"], r


def test_watcher_ping():
    dr.STATE = Path(tempfile.mkdtemp()) / "replies.json"
    sent = []
    post = lambda url, key: sent.append(key) or True
    conv = lambda age, way="inbound": [{"lastMessageDirection": way, "lastMessageDate": int((NOW - age) * 1000)}]
    with mock.patch.dict(os.environ, {"N8N_TOUR_PING_URL": "https://x", "N8N_TOUR_PING_KEY": "k"}):
        assert not dr.ping_watcher(conv(30, "outbound"), NOW, post), "staff text is not a ping"
        assert not dr.ping_watcher(conv(3 * 3600), NOW, post), "too old for the Watcher to read"
        assert dr.ping_watcher(conv(30), NOW, post) and len(sent) == 1
        assert not dr.ping_watcher(conv(30), NOW + 60, post), "same text: no second execution"
        assert not dr.ping_watcher(conv(10), NOW + 60, post), "burst: held by the gap"
        assert dr.ping_watcher(conv(-200), NOW + 400, post) and len(sent) == 2, "held text goes after the gap"
        assert not dr.ping_watcher(conv(-700), NOW + 800, lambda u, k: False), "failed ping is not seen"
        assert dr.ping_watcher(conv(-700), NOW + 860, post) and len(sent) == 3, "...so it retries"
    with mock.patch.dict(os.environ, {"N8N_TOUR_PING_URL": "", "N8N_TOUR_PING_KEY": ""}):
        assert not dr.ping_watcher(conv(30), NOW + 2000, post), "unset = off"


if __name__ == "__main__":
    os.environ.setdefault("FORGE_ACTION_LOG", str(Path(tempfile.mkdtemp()) / "a.jsonl"))
    test_watcher_ping()
    test_channel_dnd()
    test_gate()
    test_flags()
    test_sweep_and_approve()
    test_auto_send()
    test_owner_handoff()
    test_quote_only_on_owner_tap()
    test_send_quote_button_end_to_end()
    test_pricing_card_layout_and_retry()
    test_age_from_website_form()
    test_ai_down_stops_sweep()
    print("test_daycare_replies: all passed")
