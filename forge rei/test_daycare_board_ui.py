"""Run with python3 test_daycare_board_ui.py — static seam guards for the Solomon · Board UI (desktop card in
daycare.jsx + the mobile Home block in mobile/m_biz_daycare.jsx). valjsx proves the JSX parses; this proves
the card is wired, hits the right routes, shows the failed-source banner and can't white-screen. Exit 1 on failure."""
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
DESK, MOB = HERE / "daycare.jsx", HERE / "mobile" / "m_biz_daycare.jsx"
ALL_JSX = list(HERE.glob("*.jsx")) + list(HERE.glob("mobile/*.jsx"))
_DECL = re.compile(r"\buse(?:State|Effect|Callback|Ref|Memo)\s*:\s*(\w+)")


def check():
    d, m = DESK.read_text(), MOB.read_text()
    card = d[d.index("function DbdBoard()"):d.index("// --- /BOARD ---")]
    dash = d[d.index("function DaycareDashboard()"):]
    assert "<DbdBoard/>" in dash.split("function DaycareSettings")[0], "board card not on the Daycare Dashboard"
    for s in ('DcxUseResource("/board?limit=', 'DcxRequest("/board/" + kind', 'dbdAct("run")', 'dbdAct("snooze", { id: i.id, hours: 24 })',
              'dbdAct("done", { id: i.id })', "Run round now", "Snooze 24h", ">Done<", "Solomon · Board",
              "Nothing open — last round", "(i.evidence || {}).source", "(i.evidence || {}).window", "i.center",
              "dc-severity-pill", "DldDuration(i.ageSec)", "data.mailDesk", "unread daycare mail", "m.subject", "m.from", "m.bucket"):
        assert s in card, ("board card missing", s)
    assert "Gmail read failed\") + \" — 0 mail items is Unknown, not zero" in d, "failed-source banner (Gmail)"
    assert "is Unknown, not zero" in d.split("function DbdSourceLine")[1].split("function DbdBoard")[0]
    assert "filter((s) => !s.ok)" in card and "DbdSourceLine(s)" in card, "failed sources must render a banner"
    for pat in (r"\[\[\"urgent\"", r"\"high\"", r"\"normal\"", r"\"low\""):
        assert re.search(pat, d.split("const DBD_SEV")[1].split("\n")[0]), ("severity groups", pat)
    assert "dangerouslySetInnerHTML" not in card, "mail subjects are third-party text — render as text only"
    assert "<a " not in card and "href=" not in card, "inbox sub-list is link text only"

    for s in ('window.useApiM("/api/daycare/board?limit=5"', 'window.apiPostM("/api/daycare/board/run", {})',
              'title="Board"', "Run round", "Unknown, not zero", "(bdv.items || []).map", "(bdv.counts || {}).open"):
        assert s in m, ("mobile board block missing", s)

    for name, src in (("daycare.jsx", d), ("m_biz_daycare.jsx", m)):
        assert not re.search(r"<\w+\[", src) and not re.search(r"<\{", src), (name, "computed JSX tag")
        declared = set(_DECL.findall(src))
        used = set(re.findall(r"\b(use(?:State|Effect|Callback|Ref|Memo)[A-Z]\w*)\b", src))
        assert used <= declared, (name, "undeclared hook alias", sorted(used - declared))
        for alias in declared:            # a second declaration anywhere = const redeclared = white screen
            for f in ALL_JSX:
                if f.name != Path(name).name:
                    assert alias not in _DECL.findall(f.read_text()), (alias, "also declared in", f.name)
    for top in ("DbdBoard", "DbdSourceLine", "DBD_SEV", "DBD_SRC"):
        hits = [f.name for f in ALL_JSX if re.search(r"(?:function|const)\s+%s\b" % top, f.read_text())]
        assert hits == ["daycare.jsx"], (top, hits)

    shell = (HERE / "FORGE REI OS.html").read_text()
    assert shell.find('src="daycare.jsx"') >= 0 and shell.find('src="daycare.jsx"') < shell.find('src="app.jsx"')
    assert 'src="m_biz_daycare.jsx"' in (HERE / "mobile" / "index.html").read_text()
    print("daycare board ui OK")


if __name__ == "__main__":
    try:
        check()
    except AssertionError as e:
        print("FAIL:", e)
        sys.exit(1)
