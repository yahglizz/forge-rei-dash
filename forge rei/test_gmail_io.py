"""Daycare Gmail (gmail_io): token refresh + cache, auth-dead cache, the daycare-only gate,
plaintext threads, no secrets out, GET-only, routes wired.
Run: python3 test_gmail_io.py   (fake Google transport — no network, no real daycare.env read; exit 1 on failure)."""
import ast
import base64
import contextlib
import io
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.parse
from pathlib import Path

os.environ.setdefault("FORGE_ACTION_LOG", str(Path(tempfile.mkdtemp()) / "actions.jsonl"))
HERE = Path(__file__).parent

import gmail_io  # noqa: E402

FAKE_ENV = {"GMAIL_CLIENT_ID": "cid-123.apps.googleusercontent.com", "GMAIL_CLIENT_SECRET": "GOCSPX-clientsecretFAKE99",
            "GMAIL_REFRESH_YAHJAIR": "1//0refreshTOKENfakefakefakefake"}
ME = "yahjair@atouchofblessing.com"
KNOWN = frozenset({"seara.p@gmail.com", "dad.ross@yahoo.com"})


def b64(s):
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")      # Gmail's unpadded base64url


def msg(mid, frm, subject, snippet="", to=ME, labels=("INBOX", "UNREAD"), tid=None, payload=None):
    p = {"headers": [{"name": "From", "value": frm}, {"name": "To", "value": to},
                     {"name": "Subject", "value": subject}, {"name": "Date", "value": "Fri, 17 Oct 2026 10:00 -0400"}]}
    p.update(payload or {})
    return {"id": mid, "threadId": tid or "t" + mid, "labelIds": list(labels), "snippet": snippet,
            "internalDate": "1792252800000", "payload": p}


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeGoogle:
    """Routes by URL like Google does. Records (method, url, data) for every request."""

    def __init__(self, msgs=(), threads=None):
        self.msgs = {m["id"]: m for m in msgs}
        self.threads = threads or {}
        self.calls, self.tokens = [], 0
        self.token_status, self.api_status, self.api_401_once = 200, None, False

    def __call__(self, req, timeout):
        url, method = req.full_url, req.get_method()
        self.calls.append((method, url, req.data))
        if url == gmail_io.TOKEN_URL:
            if self.token_status != 200:
                raise urllib.error.HTTPError(url, self.token_status, "bad", {}, io.BytesIO(
                    b'{"error":"invalid_grant","error_description":"SECRETBODY upstream detail"}'))
            self.tokens += 1
            return Resp(json.dumps({"access_token": f"ya29.SECRETaccess{self.tokens}xxxxxxxx",
                                    "expires_in": 3600}).encode())
        assert req.get_header("Authorization", "").startswith("Bearer ya29."), "API call without the access token"
        if self.api_401_once:
            self.api_401_once = False
            raise urllib.error.HTTPError(url, 401, "expired", {}, io.BytesIO(b"SECRETBODY"))
        if self.api_status:
            raise urllib.error.HTTPError(url, self.api_status, "boom", {}, io.BytesIO(b"SECRETBODY ya29.leak"))
        u = urllib.parse.urlparse(url)
        q = urllib.parse.parse_qs(u.query)
        parts = u.path.split("/users/me/", 1)[1].split("/")
        if parts == ["messages"]:
            return Resp(json.dumps({"messages": [{"id": k, "threadId": v["threadId"]} for k, v in self.msgs.items()],
                                    "nextPageToken": "NEXTPAGE"}).encode())
        if parts[0] == "messages":
            m = dict(self.msgs[parts[1]])
            m["payload"] = {"headers": m["payload"]["headers"]}            # metadata = headers only
            return Resp(json.dumps(m).encode())
        if parts[0] == "threads":
            ms = self.threads.get(parts[1])
            if ms is None:
                raise urllib.error.HTTPError(url, 404, "nf", {}, io.BytesIO(b""))
            if q.get("format") == ["metadata"]:
                ms = [dict(m, payload={"headers": m["payload"]["headers"]}) for m in ms]
            return Resp(json.dumps({"id": parts[1], "messages": ms}).encode())
        raise AssertionError(f"unexpected Google call {method} {url}")

    def api(self):
        return [c for c in self.calls if c[1].startswith(gmail_io.API)]


def install(fake, env=FAKE_ENV):
    gmail_io._urlopen = fake
    gmail_io._env = lambda: {}                       # never the real daycare.env
    for k in FAKE_ENV:
        os.environ.pop(k, None)
    os.environ.update(env)
    gmail_io._TOK.update(access="", exp=0.0)
    gmail_io._DEAD[0] = 0.0
    gmail_io._KNOWN.update(at=0.0, emails=frozenset())
    return fake


KEEP = [  # (message, expected bucket)
    (msg("m000001", "Seara Peterson <Seara.P@gmail.com>", "Mia pickup Friday", "Grandma picks Mia up at 4"), "parent"),
    (msg("m000002", "dad.ross@yahoo.com", "Question about my invoice", "Was I charged twice?"), "billing"),
    (msg("m000003", "noreply@atouchofblessing.com", "New Family Contact Form", "A family submitted the form"), "lead"),
    (msg("m000004", "Jen <jen.new@gmail.com>", "Looking for daycare", "Do you have openings for my 2 year old son?"), "lead"),
    (msg("m000005", "kim@outlook.com", "Tuition question", "How much is weekly tuition?"), "billing"),
    (msg("m000006", "ra-ocdel@pa.gov", "Annual inspection", "Child care certification inspection next week"), "licensing"),
    (msg("m000007", "receipts@stripe.com", "Payment received — A Touch of Blessings", "You received $250.00"), "billing"),
    (msg("m000008", "notify@supabase.io", "Project eqblpbeqothkpyqiafzs nearing its quota", "Usage 85%"), "system"),
    (msg("m000009", "sales@kaplanco.com", "Classroom supplies for your preschool", "Fall catalog"), "vendor"),
    (msg("m000010", "Ana <ana@icloud.com>", "Re: tour", "Can we tour Tuesday? My daughter is 3"), "lead"),
]
DROP = [
    msg("m000101", "Verizon <alerts@verizon.com>", "Your Verizon bill is ready", "Amount due $89.12"),
    msg("m000102", "Verizon <deals@verizon.com>", "Deals for daycare owners", "Childcare centers save 20%"),
    msg("m000103", "Vercel <billing@vercel.com>", "Your invoice for October", "Invoice #V-1234 $20.00"),
    msg("m000104", "Vercel <notifications@vercel.com>", "Deployment failed", "forge-site build error"),
    msg("m000105", "Notion <news@notion.so>", "Join our product tour", "See what's new this fall"),
    msg("m000106", "Square <messaging@squareup.com>", "You sent a payment of $50.00 to Jane Doe", "Receipt"),
    msg("m000107", "Google Search Console <sc-noreply@google.com>", "New issue detected for atouchofblessing.com",
        "Core Web Vitals"),
    msg("m000108", "receipts@stripe.com", "Your receipt from Vercel Inc.", "Amount paid $20.00"),
    msg("m000109", "advertise-noreply@support.facebook.com", "Boost your business with Meta ads", "Get more reach"),
    msg("m000110", "newsletter@substack.com", "Weekly roundup", "Ten things this week"),
]


# ── token ──────────────────────────────────────────────────────────────────────────────
def test_token_refresh_is_cached_and_renewed():
    f = install(FakeGoogle(msgs=[KEEP[0][0]]))
    assert gmail_io.mail_view(known=KNOWN)["ok"] and gmail_io.mail_view(known=KNOWN)["ok"]
    tok_calls = [c for c in f.calls if c[1] == gmail_io.TOKEN_URL]
    assert len(tok_calls) == 1, "one refresh, then the cached access token"
    form = urllib.parse.parse_qs(tok_calls[0][2].decode())
    assert form["grant_type"] == ["refresh_token"] and form["refresh_token"] == [FAKE_ENV["GMAIL_REFRESH_YAHJAIR"]]
    gmail_io._TOK["exp"] = gmail_io.time.time() + 30            # inside the 60 s skew → refresh again
    gmail_io.mail_view(known=KNOWN)
    assert f.tokens == 2
    f.api_401_once = True                                       # Google expired it early → one fresh token
    assert gmail_io.mail_view(known=KNOWN)["ok"] and f.tokens == 3


def test_auth_dead_is_cached_15_min():
    f = install(FakeGoogle(msgs=[KEEP[0][0]]))
    f.token_status = 400
    out = gmail_io.mail_view(known=KNOWN)
    assert out["ok"] is False and out["configured"] is False and out["authDead"] is True, out
    assert "re-consent" in out["error"] and "SECRETBODY" not in json.dumps(out) and "invalid_grant" not in out["error"]
    n = len(f.calls)
    for fn in (lambda: gmail_io.mail_view(known=KNOWN), lambda: gmail_io.thread_view("tm000001", known=KNOWN)):
        o = fn()
        assert o["ok"] is False and o["authDead"], o
    assert len(f.calls) == n, "while dead, no call reaches Google"
    assert 14 * 60 < gmail_io._DEAD[0] - gmail_io.time.time() <= 15 * 60
    gmail_io._DEAD[0] = 0.0
    f.token_status = 200
    assert gmail_io.mail_view(known=KNOWN)["ok"], "recovers once the dead window passes"


def test_not_configured_makes_no_call():
    f = install(FakeGoogle(), env={})
    assert not gmail_io.configured()
    for out in (gmail_io.mail_view(), gmail_io.thread_view("tm000001")):
        assert out == {**out, "ok": False, "configured": False, "via": "gmail"} and "GMAIL_" in out["error"], out
    assert f.calls == []


def test_google_errors_are_typed_and_clean():
    f = install(FakeGoogle(msgs=[KEEP[0][0]]))
    f.api_status = 503
    out = gmail_io.mail_view(known=KNOWN)
    assert out["ok"] is False and out["configured"] is True and out["error"] == "Gmail HTTP 503", out
    assert "SECRETBODY" not in json.dumps(out) and "ya29" not in json.dumps(out)
    try:
        gmail_io._get("/messages")
    except gmail_io.GmailError as e:
        assert e.__cause__ is None and e.__suppress_context__, "upstream error never chained into the exception"
    assert issubclass(gmail_io.GmailAuthError, gmail_io.GmailError)


# ── the daycare-only gate ──────────────────────────────────────────────────────────────
def test_filter_keeps_daycare_and_drops_everything_else():
    f = install(FakeGoogle(msgs=[m for m, _ in KEEP] + DROP))
    out = gmail_io.mail_view(days=7, limit=50, known=KNOWN | {"hidden.parent@x.com"})
    got = {r["id"]: r["bucket"] for r in out["rows"]}
    assert got == {m["id"]: b for m, b in KEEP}, got
    assert out["filteredOut"] == len(DROP) and out["count"] == len(KEEP), out
    s = json.dumps(out)
    for word in ("Verizon", "Vercel", "Notion", "Square", "Search Console", "Boost your business", "substack",
                 "Jane Doe"):
        assert word not in s, f"{word} leaked out of the module"
    assert "dad.ross@yahoo.com" in s and "hidden.parent" not in s, \
        "a sender's own From header shows; the known-guardian set itself is never in the payload"
    assert len(f.api()) == 1 + len(KEEP) + len(DROP), "one list + one metadata GET per message"
    assert set(out) >= {"ok", "via", "rows", "filteredOut", "dateRange", "fetchedAt", "unreadCount", "count"}
    assert out["via"] == "gmail" and out["unreadCount"] == len(KEEP) and out["nextPage"] == "NEXTPAGE"
    import telegram_agent as ta
    assert ta.redact(out, pin=True)["nextPage"] == "NEXTPAGE", "the model can page: no 'token' key for redact to eat"
    assert out["dateRange"]["days"] == 7 and out["dateRange"]["since"] < out["dateRange"]["until"]
    r = out["rows"][0]
    assert set(r) == {"id", "threadId", "date", "from", "to", "subject", "snippet", "labels", "unread", "bucket"}, r
    assert r["date"].startswith("2026-") and r["unread"] is True
    # bucket narrowing + validation
    b = gmail_io.mail_view(bucket="billing", known=KNOWN)
    assert {x["bucket"] for x in b["rows"]} == {"billing"} and b["count"] == 3, b
    assert "bucket must be one of" in gmail_io.mail_view(bucket="noise", known=KNOWN)["error"]
    # the known set is lazily built: a callable is only called when Gmail is usable
    called = []
    gmail_io.mail_view(known=lambda: called.append(1) or KNOWN)
    assert called == [1]
    install(FakeGoogle(), env={})
    gmail_io.mail_view(known=lambda: called.append(2) or KNOWN)
    assert called == [1], "no GHL contact paging when Gmail isn't even configured"


def test_filter_rules_direct():
    df = gmail_io.daycare_filter
    assert df({"from": "x@y.com", "to": "noreply@atouchofblessing.com", "subject": "fwd"}) == "lead", "recipient rule"
    assert df({"from": "Mom <MOM@x.com>", "subject": "hi"}, {"mom@x.com"}) == "parent"
    assert df({"from": "mom@x.com", "subject": "hi"}) is None, "unknown sender, no daycare words"
    assert df({"from": "a@b.com", "subject": "Your invoice", "snippet": "for services"}) is None, "weak word alone"
    assert df({"from": "a@b.com", "subject": "Invoice", "snippet": "for my son's care"}) == "billing", "weak + child"
    assert df({"from": "a@b.com", "subject": "A Mother’s Touch", "snippet": "hello"}) == "vendor", "curly apostrophe"
    assert df({"from": "alerts@verizon.com", "subject": "A Touch of Blessings bill"}) is None, "noise always drops"
    assert df({"from": "", "subject": "tuition"}) is None
    assert df({"from": "x@stripe.com", "subject": "Dispute opened", "snippet": "a touch of blessing 2 & 3"}) == "billing"
    assert df({"from": "x@business.facebook.com", "subject": "Ad rejected", "snippet": "act 1175564690150627"}) == "system"
    q = gmail_io.daycare_query(7, "from:kim@outlook.com\nOR x")
    assert q.startswith("newer_than:7d -category:promotions") and q.endswith("(from:kim@outlook.com OR x)"), q
    assert "-in:sent" in q and "\n" not in q
    for v in ("../x", "a/b", "", "x" * 65, "abc"):
        try:
            gmail_io._valid_id(v)
            raise AssertionError(f"bad id accepted: {v!r}")
        except gmail_io.GmailError:
            pass


# ── threads ────────────────────────────────────────────────────────────────────────────
def test_thread_plaintext_html_strip_and_truncation():
    html_body = ("<html><head><style>p{color:red}</style><title>T</title></head><body><p>Hi&nbsp;Ms.&amp;Mr.</p>"
                 "<script>steal()</script><div>Mia&#39;s   tuition</div><br>thanks</body></html>")
    alt = {"mimeType": "multipart/alternative", "parts": [
        {"mimeType": "text/plain", "body": {"data": b64("Plain wins.\n\n\n   Second   line")}},
        {"mimeType": "text/html", "body": {"data": b64("<p>HTML LOSES</p>")}}]}
    html_only = {"mimeType": "multipart/mixed", "parts": [
        {"mimeType": "text/html", "body": {"data": b64(html_body)}},
        {"mimeType": "application/pdf", "filename": "invoice.pdf", "body": {"data": b64("PDFBYTES")}}]}
    long_body = {"mimeType": "text/plain", "body": {"data": b64("tuition " * 1000)}}
    f = install(FakeGoogle(threads={
        "tm000001": [msg("m000001", "seara.p@gmail.com", "Mia", payload=html_only),
                     msg("m000011", ME, "Re: Mia", payload=alt)],
        "tm000002": [msg("m000002", "seara.p@gmail.com", "Long", payload=long_body)]}))
    t = gmail_io.thread_view("tm000001", known=KNOWN)
    assert t["ok"] and t["count"] == 2 and t["bucket"] == "parent" and not t["truncated"], t
    txt = t["text"]
    assert "Hi Ms.&Mr." in txt and "Mia's tuition" in txt and "thanks" in txt, txt
    for bad in ("<p>", "steal()", "color:red", "PDFBYTES", "HTML LOSES", "&nbsp;", "&#39;", "   "):
        assert bad not in txt, (bad, txt)
    assert "Plain wins.\nSecond line" in txt, txt
    assert t["messages"][0] == {"id": "m000001", "date": t["messages"][0]["date"], "from": "seara.p@gmail.com",
                                "to": ME, "subject": "Mia", "unread": True}
    long = gmail_io.thread_view("tm000002", known=KNOWN)
    assert long["truncated"] is True and len(long["text"]) == gmail_io.MAX_CHARS + 1 and long["text"].endswith("…")
    assert len(gmail_io.thread("tm000002", 100, KNOWN)["text"]) == 101
    assert gmail_io.thread_view("tm000099", known=KNOWN)["error"] == "Gmail: not found"
    assert "id must be" in gmail_io.thread_view("../../drafts", known=KNOWN)["error"]


def test_out_of_scope_thread_never_fetches_a_body():
    f = install(FakeGoogle(threads={"tm000101": [msg("m000101", "alerts@verizon.com", "Your bill", payload={
        "mimeType": "text/plain", "body": {"data": b64("VERIZON BODY")}})]}))
    out = gmail_io.thread_view("tm000101", known=KNOWN)
    assert out["ok"] is False and out.get("outOfScope") and "daycare mail" in out["error"], out
    assert "VERIZON BODY" not in json.dumps(out) and "Your bill" not in json.dumps(out)
    assert not [c for c in f.api() if "format=full" in c[1]], "the gate runs on headers; no body is fetched"


# ── hygiene ────────────────────────────────────────────────────────────────────────────
def test_no_secrets_in_output_or_logs():
    leak = ("key sk_live_ABCDEFGHIJKLMNOPQRSTUV and ya29.A0ARrdaMleakleakleak and 1//0gLEAKrefreshTOKENxxxxxx "
            "GOCSPX-leakedSecret123 Bearer abcdefghijklmnopqrstuvwxyz")
    m = msg("m000001", "seara.p@gmail.com", "tuition " + leak[:40], leak,
            payload={"mimeType": "text/plain", "body": {"data": b64("body: " + leak)}})
    f = install(FakeGoogle(msgs=[m], threads={"tm000001": [m]}))
    buf_out, buf_err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
        lst = gmail_io.mail_view(known=KNOWN)
        th = gmail_io.thread_view("tm000001", known=KNOWN)
    s = json.dumps([lst, th])
    for secret in ("sk_live_ABCDEFGH", "ya29.", "1//0gLEAK", "GOCSPX-", "abcdefghijklmnopqrstuvwxyz",
                   FAKE_ENV["GMAIL_REFRESH_YAHJAIR"], FAKE_ENV["GMAIL_CLIENT_SECRET"]):
        assert secret not in s, secret
    assert "[redacted]" in th["text"] and lst["rows"][0]["bucket"] == "billing"
    assert buf_out.getvalue() == "" and buf_err.getvalue() == "", "gmail_io never logs"
    src = (HERE / "gmail_io.py").read_text()
    assert "print(" not in src.split('if __name__ == "__main__":')[0], "no logging in the module body"
    assert not re.search(r"open\([^)]*['\"]w", src) and "write_text" not in src and "atomic_write" not in src, \
        "nothing is written to disk — no bodies at rest"


def test_read_only_get_verbs_only():
    m = KEEP[0][0]
    f = install(FakeGoogle(msgs=[m], threads={"tm000001": [m]}))
    gmail_io.mail_view(known=KNOWN)
    gmail_io.thread_view("tm000001", known=KNOWN)
    assert f.api() and all(meth == "GET" for meth, _, _ in f.api()), f.api()
    assert {(meth, url) for meth, url, _ in f.calls if not url.startswith(gmail_io.API)} == {("POST", gmail_io.TOKEN_URL)}
    src = (HERE / "gmail_io.py").read_text().split('if __name__ == "__main__":')[0]
    paths = re.findall(r'_get\(f?"([^"]+)"', src)
    assert sorted(set(paths)) == ["/messages", "/messages/{mid}", "/threads/{tid}"], paths
    assert src.count('method="POST"') == 1 and "TOKEN_URL, data=" in src, "the one POST is the token exchange"
    tree = ast.parse(src)
    docs = {id(n.body[0].value) for n in ast.walk(tree) if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef))
            and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    code_strings = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
                    and id(n) not in docs]
    for verb in ("/send", "modify", "trash", "batchDelete", "batchModify", "/drafts", "/import", "/insert", "/labels"):
        assert not [s for s in code_strings if verb in s], f"Gmail write verb {verb!r} in gmail_io code"


def test_known_emails_cache():
    import daycare_ghl
    seen = []
    rows = [{"email": "Seara.P@Gmail.com", "additionalEmails": [{"email": "S2@x.com"}, "s3@x.com"]},
            {"email": ""}, {"email": "not-an-email"}, {}]
    real = daycare_ghl.iter_contacts
    install(FakeGoogle())
    try:
        daycare_ghl.iter_contacts = lambda c, **k: seen.append(1) or iter(rows)
        got = gmail_io.known_emails(object())
        assert got == frozenset({"seara.p@gmail.com", "s2@x.com", "s3@x.com"}), got
        assert gmail_io.known_emails(object()) is got and seen == [1], "cached 10 min"
        gmail_io._KNOWN["at"] -= 601
        daycare_ghl.iter_contacts = lambda c, **k: (_ for _ in ()).throw(RuntimeError("GHL 429"))
        assert gmail_io.known_emails(object()) == got, "GHL down → last good set"
    finally:
        daycare_ghl.iter_contacts = real


# ── wiring ─────────────────────────────────────────────────────────────────────────────
def test_routes_registered_in_the_connector_catalog():
    """Same rule telegram_agent.catalog() applies: a quoted /api path inside _handle_daycare_get
    is a GET route — so the agents' route list picks these up with no extra code."""
    src = (HERE / "connector.py").read_text()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_handle_daycare_get")
    body = ast.get_source_segment(src, fn)
    for p in ("/api/daycare/mail", "/api/daycare/mail/thread"):
        assert f'"{p}"' in body, p
    assert "gmail_io.mail_view(" in body and "telegram_agent.redact(gmail_io.thread_view(" in body
    assert "known=lambda: gmail_io.known_emails(DAYCARE_GHL)" in body
    assert 'ROUTES["/api/actions/digest"]' in src and 'NO_CACHE.add("/api/actions/digest")' in src
    import dash_live
    import telegram_agent as ta
    assert ta.MAIL_HINT in dash_live._HINT["daycare"] and "never a reason to write" in ta.MAIL_HINT
    assert ta.path_business("/api/daycare/mail") == "daycare"


def main():
    saved = (gmail_io._urlopen, gmail_io._env, {k: os.environ.get(k) for k in FAKE_ENV})
    failed = 0
    try:
        for name, fn in list(globals().items()):
            if name.startswith("test_") and callable(fn):
                try:
                    fn()
                    print("ok  ", name)
                except Exception as e:  # noqa: BLE001
                    failed += 1
                    import traceback
                    print("FAIL", name, "->", repr(e))
                    traceback.print_exc()
    finally:
        gmail_io._urlopen, gmail_io._env = saved[0], saved[1]
        for k, v in saved[2].items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v
    print("gmail_io:", "FAILED" if failed else "all OK")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
