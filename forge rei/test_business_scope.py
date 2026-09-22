"""test_business_scope.py — the archive mechanism (P1-1, spec §21 Archive Test).

ARCHIVE -> hidden from active lists -> data remains -> REACTIVATE -> returns.
Runs against a temp store; never touches marcus_state/.

Run directly: python3 test_business_scope.py
"""
import json
import tempfile
from pathlib import Path

import business_scope as bs


def main():
    with tempfile.TemporaryDirectory() as tmp:
        bs.STATE = Path(tmp) / "businesses.json"

        # Default seed when the file is missing — and nothing written yet.
        assert bs.archived() == {"dropship", "agency:p"}, bs.archived()
        assert not bs.STATE.exists()
        ids = [b["id"] for b in bs.listing()]
        assert ids == ["rei", "agency", "daycare", "dropship", "agency:p"], ids
        active = [b["id"] for b in bs.listing() if not b["archived"]]
        assert active == ["rei", "agency", "daycare"], active

        # A business's own data store, standing in for dropship.json.
        data = Path(tmp) / "dropship.json"
        data.write_text(json.dumps({"watchlist": [1, 2, 3]}))

        # Reactivate -> returns; data untouched.
        r = bs.set_archived("dropship", False)
        assert r["ok"] and not bs.is_archived("dropship"), r
        assert "dropship" in [b["id"] for b in r["businesses"] if not b["archived"]]
        assert json.loads(data.read_text()) == {"watchlist": [1, 2, 3]}
        assert json.loads(bs.STATE.read_text()) == {"archived": ["agency:p"]}

        # Archive -> hidden again; data still there. Idempotent.
        assert bs.set_archived("dropship", True)["ok"]
        assert bs.set_archived("dropship", True)["ok"]
        assert bs.is_archived("dropship")
        assert json.loads(bs.STATE.read_text()) == {"archived": ["dropship", "agency:p"]}
        assert json.loads(data.read_text()) == {"watchlist": [1, 2, 3]}

        # Lens round-trip.
        assert bs.set_archived("agency:p", False)["ok"] and not bs.is_archived("agency:p")
        assert bs.set_archived("agency:p", True)["ok"] and bs.is_archived("agency:p")

        # Unknown / bad input rejected, store unchanged.
        before = bs.STATE.read_text()
        for bad in ("amazon", "", None, "agency:x", ["rei"], {"id": "rei"}):
            assert "error" in bs.set_archived(bad, True), bad
        assert "error" in bs.set_archived("rei", "yes")
        assert not bs.is_archived("amazon") and not bs.is_archived(None)
        assert bs.STATE.read_text() == before

        # Corrupt file -> fail back to the seed instead of crashing.
        bs.STATE.write_text("{not json")
        assert bs.archived() == {"dropship", "agency:p"}
        # Unknown ids hand-edited into the file are ignored.
        bs.STATE.write_text(json.dumps({"archived": ["dropship", "amazon"]}))
        assert bs.archived() == {"dropship"}

    print("test_business_scope: OK")


def consumers():
    """The backend consumers skip archived businesses — and come back on reactivate.
    Stubs stand in for every live store/agent, so nothing real is read or written."""
    import sys
    import types

    import agent_bus
    import agent_coach
    import mission_control as mc
    import mission_control_agent as mca

    with tempfile.TemporaryDirectory() as tmp:
        bs.STATE = Path(tmp) / "businesses.json"   # default seed: dropship archived
        agent_bus.STATE = Path(tmp) / "agent_bus.json"
        called = []

        # Mission Control: no dropship card, and so no Shopify/AutoDS health pings.
        def stub(bid):
            def build(*_a):
                called.append(bid)
                return mc._card(bid, bid, "", "#000", "Dashboard")
            return build
        for bid in ("rei", "agency", "daycare", "dropship"):
            setattr(mc, f"_{bid}_card", stub(bid))
        snap = mc.snapshot()
        assert [c["id"] for c in snap["businesses"]] == ["rei", "agency", "daycare"], snap
        assert "dropship" not in called and snap["archived"] == ["agency:p", "dropship"]

        # Orion: dropship never read, never sent to the paid brief.
        for name, attrs in {
            "agency_agents": {"status": lambda: {}},
            "agency_requests_io": {"list_requests": lambda: {"requests": []}},
            "agency_approvals_io": {"list_queue": lambda _s: {"queue": []}},
            "dropship_io": {"stats": lambda: called.append("dropship_io") or {}},
        }.items():
            sys.modules[name] = types.SimpleNamespace(**attrs)
        midas = types.SimpleNamespace(status=lambda: called.append("midas") or {},
                                      brief=lambda: {})
        data = mca.OrionEngine()._gather(midas=midas)
        assert "dropship" not in data and data["archived"] == ["agency:p", "dropship"]
        assert "midas" not in called and "dropship_io" not in called

        # Coaching: Midas gets no peer lessons, and his don't reach active agents.
        msgs = [{"kind": "coach", "from": "midas", "to": "all", "text": "m"},
                {"kind": "coach", "from": "dyson", "to": "all", "text": "d"}]
        agent_coach._coach_messages = lambda limit=200: msgs
        assert agent_coach.insights_for("midas") == []
        assert [i["from"] for i in agent_coach.insights_for("scout")] == ["dyson"]

        # Reactivate -> everything returns.
        bs.set_archived("dropship", False)
        called.clear()
        assert "dropship" in [c["id"] for c in mc.snapshot()["businesses"]]
        data = mca.OrionEngine()._gather(midas=midas)
        assert "dropship" in data and "midas" in called and "dropship_io" in called
        assert [i["from"] for i in agent_coach.insights_for("scout")] == ["midas", "dyson"]
        assert [i["from"] for i in agent_coach.insights_for("midas")] == ["dyson"]

    print("test_business_scope consumers: OK")


if __name__ == "__main__":
    main()
    consumers()
