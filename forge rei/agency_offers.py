"""agency_offers.py — the ClientForge offer sheet (single source of truth).

These are the packages the operator quotes on a live call, surfaced in the Call
Center's Interested screen.

**Prices here MUST match the public ClientForge site** (`~/Desktop/clientforge/
src/App.tsx`, the `Services()` component + the contact form's service <select>).
The site says "Three things. Fixed pricing." — quoting a number the prospect
can't find on the site is how a deal dies at the follow-up email.

When the site's pricing changes, change it HERE too. This module is the only
place the dashboard reads offers from.

Last synced against the site: 2026-07-29.
"""

# id: stable key stored on the lead/client. Never renumber.
OFFERS = [
    {
        "id": "website",
        "name": "Custom Website",
        "price": 350,
        "display": "$350",
        "from": True,          # site says "From $350"
        "monthly": False,
        "blurb": "Marketing site that loads instantly and converts. Built from scratch.",
        "includes": [
            "Custom design, not a template",
            "Mobile-first, blazing fast",
            "Lighthouse 95+, SEO-ready",
            "Forms, booking, Stripe",
        ],
        "service": "Website",   # maps to agency_io.SERVICES
    },
    {
        "id": "website-app",
        "name": "Website + App Combo",
        "price": 1100,
        "display": "$1,100",
        "from": True,
        "monthly": False,
        "blurb": "Website plus a matching mobile app — one brand, one system.",
        "includes": [
            "User auth & database",
            "Payments & subscriptions",
            "Admin dashboards",
            "Deploy & hand-over",
        ],
        "service": "Website",
    },
    {
        "id": "ai-agents",
        "name": "AI Agents",
        "price": 600,
        "display": "$600",
        "from": True,
        "monthly": False,
        "blurb": "Trained assistants that run part of the business — leads, follow-ups, daily tasks.",
        "includes": [
            "Lead management & follow-up",
            "CRM updates & inbox handling",
            "Client onboarding & support",
            "Daily workflow execution",
        ],
        "service": "Automations",
    },
]

_BY_ID = {o["id"]: o for o in OFFERS}


def list_offers():
    return {"ok": True, "offers": OFFERS,
            "source": "clientforge site — Services() in src/App.tsx"}


def get(offer_id):
    return _BY_ID.get(str(offer_id or ""))


def normalize(sel):
    """Turn whatever the UI sent into a stored offer dict.

    A catalog pick is looked up by id so the operator can't quote a price the
    site doesn't show. A custom deal is taken as typed — closing a growth deal
    below list is the operator's call (he said so), but it gets LABELLED custom
    so the pipeline never reads it as standard pricing.
    """
    if not isinstance(sel, dict):
        return None
    if sel.get("custom"):
        name = str(sel.get("name") or "Custom deal").strip()[:80]
        try:
            price = max(0.0, float(sel.get("price") or 0))
        except (TypeError, ValueError):
            price = 0.0
        return {
            "id": "custom",
            "custom": True,
            "name": name,
            "price": price,
            "monthly": bool(sel.get("monthly")),
            "includes": str(sel.get("includes") or "").strip()[:400],
        }
    found = get(sel.get("id"))
    if not found:
        return None
    return {
        "id": found["id"],
        "custom": False,
        "name": found["name"],
        "price": float(found["price"]),
        "monthly": found["monthly"],
        "includes": ", ".join(found["includes"]),
        "service": found.get("service", ""),
    }


def line(offer):
    """One-line human summary for a note / pipeline record."""
    if not offer:
        return ""
    money = f"${offer['price']:,.0f}" + ("/mo" if offer.get("monthly") else "")
    tag = " (CUSTOM — off the published sheet)" if offer.get("custom") else ""
    return f"{offer['name']} — {money}{tag}"


if __name__ == "__main__":
    assert len(OFFERS) == 3
    assert [o["price"] for o in OFFERS] == [350, 1100, 600], "must match the live site"
    assert {o["id"] for o in OFFERS} == {"website", "website-app", "ai-agents"}
    assert all(not o["monthly"] for o in OFFERS), "site publishes no recurring offer"

    std = normalize({"id": "website-app"})
    assert std["price"] == 1100 and std["custom"] is False, std
    assert line(std) == "Website + App Combo — $1,100", line(std)

    cus = normalize({"custom": True, "name": " Starter bundle ", "price": "175",
                      "monthly": True, "includes": "site + 1 automation"})
    assert cus["price"] == 175 and cus["monthly"] and cus["name"] == "Starter bundle", cus
    assert line(cus) == "Starter bundle — $175/mo (CUSTOM — off the published sheet)", line(cus)

    assert normalize({"id": "nope"}) is None
    assert normalize(None) is None
    assert normalize({"custom": True, "price": "abc"})["price"] == 0.0
    assert line(None) == ""
    print("ok")