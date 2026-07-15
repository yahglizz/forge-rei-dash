import sys
sys.path.insert(0, ".")
import telegram_io as tg

_bad = False
def check(name, cond):
    global _bad
    print(("PASS" if cond else "FAIL"), name)
    if not cond: _bad = True

# 1. new client edit request event
m1 = {"from": "portal", "to": "all", "kind": "note",
      "text": "New edit request from Bloom Dental: Swap hero",
      "data": {"type": "edit_request", "requestId": "r42", "client": "Bloom Dental",
               "title": "Swap hero image", "reqType": "Website Edit", "priority": "high",
               "detail": "New photo + headline please"}}
cls1 = tg._event_class(m1)
check("edit_request classified", cls1 == "edit_request")
btns1 = tg._buttons_for(cls1, m1["data"])
flat1 = [b["callback_data"] for row in (btns1 or []) for b in row]
check("edit_request has Plan-with-Dyson button", "dysonplan:r42" in flat1)
check("edit_request has Dismiss button", "reqdismiss:r42" in flat1)
txt1 = tg._compose_text(m1, m1["data"])
check("edit_request text mentions client + title", "Bloom Dental" in txt1 and "Swap hero image" in txt1)

# 2. Dyson plan event
m2 = {"from": "dyson", "to": "all", "kind": "note",
      "text": "Dyson drafted a plan for Bloom Dental: Swap hero",
      "data": {"type": "dyson_plan", "draftId": "d99", "requestId": "r42",
               "client": "Bloom Dental", "title": "Swap hero image", "risk": "low",
               "summary": "Replace hero img + headline on index.", "steps": ["Backup", "Swap img", "Publish"]}}
cls2 = tg._event_class(m2)
check("dyson_plan classified", cls2 == "dyson_plan")
btns2 = tg._buttons_for(cls2, m2["data"])
flat2 = [b["callback_data"] for row in (btns2 or []) for b in row]
check("dyson_plan has Approve&ship button", "dysongo:d99" in flat2)
check("dyson_plan has Reject button", "dysonno:d99" in flat2)
txt2 = tg._compose_text(m2, m2["data"])
check("dyson_plan text shows plan steps", "Swap img" in txt2 and "risk" in txt2.lower())

# 3. default toggles include the new event classes
check("edit_request toggle default on", tg._DEFAULT_TOGGLES.get("edit_request") is True)
check("dyson_plan toggle default on", tg._DEFAULT_TOGGLES.get("dyson_plan") is True)

# 4. result labels exist for the new actions
for a in ["dysonplan", "reqdismiss", "dysongo", "dysonno"]:
    check(f"result label for {a}", tg._result_text(a, {}) not in ("", None))

print("\nRESULT:", "ALL GREEN" if not _bad else "HAS FAILURES")
