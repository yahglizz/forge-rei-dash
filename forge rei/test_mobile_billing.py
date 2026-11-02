"""Static checks for the phone Billing tab (mobile/m_biz_billing.jsx). No network, nothing live.
Run: python3 test_mobile_billing.py   Exit 1 on failure."""
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
M = HERE / "mobile"
NEW = M / "m_biz_billing.jsx"
CSS_MARK = "/* ===== Billing tab (m_biz_billing.jsx)."
CSS_END = "/* ===== end Billing tab ===== */"
_DECL = re.compile(r"const\s*\{([^}]*)\}\s*=\s*React\s*;")


def aliases(src):
    out = set()
    for body in _DECL.findall(src):
        out |= set(re.findall(r":\s*(\w+)", body))
    return out


def check():
    assert NEW.exists(), "m_biz_billing.jsx missing"
    src = NEW.read_text()
    daycare = (M / "m_biz_daycare.jsx").read_text()
    html = (M / "index.html").read_text()

    # script tag order: billing before daycare, exactly once
    tag = '<script type="text/babel" src="m_biz_billing.jsx"></script>'
    assert html.count(tag) == 1, "billing script tag must appear once"
    assert html.index(tag) < html.index('src="m_biz_daycare.jsx"'), "billing must load before daycare"
    assert html.index('src="m_shell.jsx"') < html.index(tag), "shell loads first"

    # one Babel scope: own aliases (suffix MBL) declared once, used nowhere else; MBL* names unique
    mine = aliases(src)
    assert mine and all(a.endswith("MBL") for a in mine), mine
    assert len(_DECL.findall(src)) == 1, "hook aliases declared once"
    used = set(re.findall(r"\b(use(?:State|Effect|Ref|Memo|Callback)[A-Z]\w*)\b", src))
    assert used <= mine, ("undeclared hook alias", sorted(used - mine))
    others = [f for f in M.glob("m_*.jsx") if f != NEW]
    for f in others:
        t = f.read_text()
        assert not (aliases(t) & mine), (f.name, "redeclares a billing alias")
        for a in mine:
            assert not re.search(r"\b%s\b" % a, t), (a, "used in", f.name)
    tops = set(re.findall(r"^(?:async\s+)?(?:function|const)\s+(\w+)", src, re.M))
    assert tops and all(n.startswith("MBL") for n in tops), sorted(n for n in tops if not n.startswith("MBL"))
    for f in others:
        t = f.read_text()
        for n in tops:
            assert not re.search(r"^(?:async\s+)?(?:function|const)\s+%s\b" % n, t, re.M), (n, "also defined in", f.name)
    assert not re.search(r"<\w+\[", src) and not re.search(r"<\{", src), "computed JSX tag"

    # exports + tab registration + thread button + A Touch of Blessings default
    assert re.search(r"Object\.assign\(window,\s*\{\s*MBLBilling,\s*MBLFeeSheet\s*\}\)", src)
    assert '{ key: "billing", label: "Billing", ico: "Dollar" }' in daycare, "billing tab missing"
    keys = re.findall(r'\{ key: "(\w+)", label', daycare.split("window.M_BIZ.daycare = ")[-1])
    assert keys.index("families") + 1 == keys.index("billing"), keys
    assert "billing: window.MBLBilling" in daycare
    for name in ("MBDHead", "MBDSheet", "MBDAuth", "MBDAuthLine"):
        assert re.search(r"Object\.assign\(window,\s*\{[^}]*\b%s\b" % name, daycare), name + " not exported"
    thread = daycare.split("function MBDThread")[1].split("function MBDMessages")[0]
    assert "window.MBLFeeSheet" in thread and "Fee link" in thread
    assert "contactId={t.contactId}" in thread and "name={t.name}" in thread
    assert "mbd-pill ghost" in thread, "44px pill button"
    home = daycare.split("function MBDHome")[1].split("// ---------------------------------------------------------------- Messages")[0]
    assert "m_bd_atob" in home and "switchTo(MBD_ATOB)" in home and "locs.data.ok" in home
    assert 'const MBD_ATOB = "11111111-1111-1111-1111-111111111111"' in daycare
    assert 'useStateMBL("atob")' in src and "localStorage" not in src and "sessionStorage" not in src, \
        "scope is never persisted"

    # every text-sending POST is behind a window.confirm in the same function
    funcs = re.split(r"\n(?=(?:async )?function \w+)", src)
    sends = 0
    for fn in funcs:
        for m in re.finditer(r'apiPostM\(\s*"([^"]+)"', fn):
            if m.group(1).endswith(("/link/send", "/ghl/reply")):
                sends += 1
                before = fn[:m.start()]
                assert "window.confirm(" in before, ("send without confirm", m.group(1))
                assert "This sends a real text." in before, "confirm must say it sends a real text"
    assert sends == 2, ("expected the 2 text routes", sends)
    allposts = set(re.findall(r'apiPostM\(\s*"([^"]+)"', src))
    assert allposts == {"/api/daycare/billing/fee-link", "/api/daycare/billing/link/compose",
                        "/api/daycare/billing/link/send", "/api/daycare/ghl/reply"}, allposts
    assert "method:" not in src, "the only raw fetch is a GET"

    # every route the file calls exists in connector.py, and the header comment lists it
    conn = (HERE / "connector.py").read_text()
    head = src.split("const {")[0]
    routes = set(re.findall(r'"(/api/daycare/[\w/\-]+)', src))
    assert len(routes) >= 7, routes
    for r in sorted(routes):
        assert ('"%s"' % r) in conn, ("route not in connector.py", r)
        assert r in head, ("header comment missing route", r)

    # CSS: appended block at the very end, dark only
    css = (M / "mobile.css").read_text()
    assert css.count(CSS_MARK) == 1 and css.rstrip().endswith(CSS_END), "billing CSS must be the last block"
    block = css[css.index(CSS_MARK):]
    assert not re.search(r"background[^;}]*(#fff\b|#ffffff\b|\bwhite\b|cream|#f[0-9a-f]{5}\b)", block, re.I), \
        "light background in billing CSS"
    assert not re.search(r"min-width:\s*42px", block), "min-width:42px is banned"
    assert "mbl-chips .m-chip" in block and "min-height: 44px" in block
    assert ".mw-mark{min-width:44px;" in css and ".m-cards button" in css, "other tests' lines untouched"
    print("mobile billing OK")


if __name__ == "__main__":
    try:
        check()
    except AssertionError as e:
        print("FAIL:", e)
        sys.exit(1)
