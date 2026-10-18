"""Run with python3 test_chat_actions_ui.py — static seam guards for the shared ChatActions UI.

valjsx only proves the JSX parses; it can't see a missing script tag, an unwired consumer or a
reused hook alias (white screen). Exit 1 on failure."""
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
CONSUMERS = ("agents_hub.jsx", "orion_office.jsx", "dashboard.jsx", "mobile/m_agents.jsx")
SHELLS = {"FORGE REI OS.html": ("chat_actions.jsx", "dashboard.jsx", "agents_hub.jsx", "orion_office.jsx"),
          "mobile/index.html": ("../chat_actions.jsx", "m_agents.jsx")}


def check():
    src = (HERE / "chat_actions.jsx").read_text()
    assert re.search(r"Object\.assign\(window,\s*\{[^}]*\bChatActions\b", src), "ChatActions not exposed on window"
    assert "/api/chat/action/" in src and "confirm" in src and "cancel" in src
    assert not re.search(r"<\w+\[", src), "computed JSX tag"          # <Icons[x] /> white-screens
    assert not re.search(r"<\{", src), "computed JSX tag"
    declared = set(re.findall(r"use(?:State|Effect|Ref): (\w+)", src))
    used = set(re.findall(r"\b(use(?:State|Effect|Ref)[A-Z]\w*)\b", src))
    assert used <= declared, ("undeclared hook alias", sorted(used - declared))

    # hook aliases unique across every other jsx (a shared alias collides in the single Babel scope)
    for alias in declared:
        for f in list(HERE.glob("*.jsx")) + list(HERE.glob("mobile/*.jsx")):
            if f.name != "chat_actions.jsx":
                assert not re.search(r"\b%s\b" % alias, f.read_text()), (alias, "reused in", f.name)

    for name in CONSUMERS:
        s = (HERE / name).read_text()
        assert "ChatActions" in s, name + " does not render ChatActions"
        assert re.search(r"\.actions\b", s) and re.search(r"\.done\b", s), name + " ignores response .actions/.done"
        assert not re.search(r"<\w+\[", s), name + " computed JSX tag"

    for html, order in SHELLS.items():
        h = (HERE / html).read_text()
        pos = [h.find('src="%s"' % t) for t in order]
        assert all(p >= 0 for p in pos), (html, "missing script", order, pos)
        assert pos[0] < min(pos[1:]), (html, "chat_actions.jsx must load before its consumers")
    print("chat actions ui OK")


if __name__ == "__main__":
    try:
        check()
    except AssertionError as e:
        print("FAIL:", e)
        sys.exit(1)
