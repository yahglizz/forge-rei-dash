"""agency_offers.py — the ClientForge offer sheet (dashboard side).

These are the packages the operator quotes on a live call, surfaced in the Call
Center's Interested screen.

**The source of truth is `forge-agency/skills/agency-offer-sheet.md`.** That file
defines the offer; this module is the machine-readable copy of it. When the offer
changes, it changes there first, then here, then on the public site — all in one
sitting. §7 of the offer sheet is the checklist.

Two price surfaces have to agree or a deal dies at the follow-up email:

  * the recurring price (`care-plan` below) MUST match what the public site's
    care-plan add-on shows — `~/Developer/main-website/app/pricing.jsx`, the
    `ADDONS` list. The site reads "$75–$200/mo"; $129 sits inside it.
  * the one-time build tiers below MUST match that same file's `WEBSITE_PLANS`,
    `AUTO_PLANS` and `ADS_PLANS`.

The build being FREE on a call while the site lists paid tiers is deliberate,
not a mismatch — see the offer sheet §7. The monthly is what must never diverge.

Last synced against the live site (clientforge.tech) and the offer sheet:
2026-09-08.
"""

# id: stable key stored on the lead/client. Never renumber.
OFFERS = [
    # ── THE OFFER ────────────────────────────────────────────────────────────
    # Free build + recurring. This is what every call is aimed at; everything
    # below it is either an expansion rung or a fallback for a client who wants
    # to buy the build outright.
    {
        "id": "care-plan",
        "name": "Website + Care Plan",
        "price": 129,
        "display": "$129/mo",
        "from": False,          # a flat price, not a "starting at"
        "monthly": True,
        "build_price": 0,       # the build itself is free
        "min_months": 6,
        "blurb": "Build is free. $129/mo keeps it running. 6-month minimum, first "
                 "charge at launch, they own the code and domain.",
        "includes": [
            "Website built free — no deposit, no setup fee",
            "Hosting, SSL, uptime monitoring",
            "Up to 2 content edits a month, 48-hour turnaround",
            "Form + CRM delivery monitoring",
            "Speed-to-lead auto-reply + missed-call text-back",
            "Monthly one-page report",
        ],
        "service": "Website",
    },

    # ── Paid build tiers — what the public site lists ────────────────────────
    {
        "id": "web-starter",
        "name": "Starter Website",
        "price": 300,
        "display": "$300",
        "from": True,
        "monthly": False,
        "blurb": "One-page site that gets them found and collecting leads.",
        "includes": [
            "1-page high-converting website",
            "Mobile responsive design",
            "Lead capture form",
            "Free hosting setup",
        ],
        "service": "Website",
    },
    {
        "id": "web-growth",
        "name": "Growth Website",
        "price": 700,
        "display": "$700",
        "from": True,
        "monthly": False,
        "blurb": "3–5 pages with the CRM and booking wired in.",
        "includes": [
            "3–5 page website",
            "CRM integration",
            "Booking / calendar setup",
            "Automated lead follow-up",
            "Google Business + reviews wired in",
        ],
        "service": "Website",
    },
    {
        "id": "web-premium",
        "name": "Premium Website",
        "price": 1400,
        "display": "$1,400",
        "from": True,
        "monthly": False,
        "blurb": "Fully custom, unlimited pages, copywriting included.",
        "includes": [
            "Fully custom design — no template",
            "Unlimited pages",
            "Funnel-ready structure",
            "Copywriting included",
            "30 days of edits after launch",
        ],
        "service": "Website",
    },

    # ── Expansion rung 3: automations ────────────────────────────────────────
    {
        "id": "auto-basic",
        "name": "Basic Automation",
        "price": 250,
        "display": "$250",
        "from": False,
        "monthly": False,
        "blurb": "Stop losing the leads they never got back to.",
        "includes": [
            "Instant SMS / email reply to new leads",
            "Lead capture automation",
            "Missed-call text-back",
            "Notification alerts to their phone",
        ],
        "service": "Automations",
    },
    {
        "id": "auto-growth",
        "name": "Growth Automation",
        "price": 550,
        "display": "$550",
        "from": False,
        "monthly": False,
        "blurb": "A system that chases the quiet ones for them.",
        "includes": [
            "CRM pipeline setup",
            "Multi-step follow-up sequences",
            "Booking + reminder system",
            "Review request automation",
            "Lead nurturing workflows",
        ],
        "service": "CRM Setup",
    },
    {
        "id": "auto-advanced",
        "name": "Advanced Systems",
        "price": 1100,
        "display": "$1,100",
        "from": True,
        "monthly": False,
        "blurb": "Custom back-office plumbing for how they actually work.",
        "includes": [
            "AI chat / receptionist integration",
            "Custom workflow architecture",
            "Connections to their existing tools",
            "Reporting dashboard",
            "30 days of tuning after launch",
        ],
        "service": "AI Receptionist",
    },

    # ── Expansion rung 4: ads. Management fee only — client pays spend. ──────
    {
        "id": "ads-starter",
        "name": "Starter Ads",
        "price": 250,
        "display": "$250/mo",
        "from": False,
        "monthly": True,
        "ad_spend_separate": True,
        "blurb": "One campaign, run properly. Management fee only — client pays spend.",
        "includes": [
            "Campaign setup & launch",
            "2 ad creatives per month",
            "Audience targeting & setup",
            "Monthly performance report",
        ],
        "service": "Ads Management",
    },
    {
        "id": "ads-growth",
        "name": "Growth Ads",
        "price": 450,
        "display": "$450/mo",
        "from": False,
        "monthly": True,
        "ad_spend_separate": True,
        "blurb": "Actively managed against cost per lead, weekly. Client pays spend.",
        "includes": [
            "4–6 fresh creatives per month",
            "Retargeting campaigns",
            "Conversion tracking setup",
            "Weekly optimization",
            "Lead follow-up automation included",
        ],
        "service": "Ads Management",
    },
    {
        "id": "ads-scale",
        "name": "Scale Ads",
        "price": 750,
        "display": "$750/mo",
        "from": False,
        "monthly": True,
        "ad_spend_separate": True,
        "blurb": "Multi-campaign spend that needs a hand on it daily. Client pays spend.",
        "includes": [
            "Unlimited creative testing",
            "Multi-campaign / multi-audience",
            "Full funnel integration",
            "Direct line for same-day changes",
            "Bi-weekly strategy call",
        ],
        "service": "Ads Management",
    },
]

_BY_ID = {o["id"]: o for o in OFFERS}

#: The offer every call is aimed at. The UI should preselect this one.
PRIMARY_ID = "care-plan"


def list_offers():
    return {"ok": True, "offers": OFFERS, "primary": PRIMARY_ID,
            "source": "forge-agency/skills/agency-offer-sheet.md"}


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
            "buildPrice": 0.0,
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
        # A monthly offer can carry a separate one-time build charge. Ours is
        # free today, but the field has to exist or build revenue is invisible
        # the day we start charging for it.
        "buildPrice": float(found.get("build_price", 0) or 0),
        "includes": ", ".join(found["includes"]),
        "service": found.get("service", ""),
    }


def line(offer):
    """One-line human summary for a note / pipeline record."""
    if not offer:
        return ""
    money = f"${offer['price']:,.0f}" + ("/mo" if offer.get("monthly") else "")
    build = offer.get("buildPrice", 0) or 0
    if offer.get("monthly"):
        money += " + free build" if build == 0 else f" + ${build:,.0f} build"
    tag = " (CUSTOM — off the published sheet)" if offer.get("custom") else ""
    return f"{offer['name']} — {money}{tag}"


if __name__ == "__main__":
    import agency_io

    assert PRIMARY_ID in _BY_ID, "the primary offer must exist in the sheet"
    assert len(_BY_ID) == len(OFFERS), "duplicate offer id"

    primary = _BY_ID[PRIMARY_ID]
    assert primary["price"] == 129 and primary["monthly"], "offer sheet says $129/mo"
    assert primary["build_price"] == 0, "offer sheet says the build is free"
    assert primary["min_months"] == 6, "offer sheet says 6-month minimum"

    # Prices that must match the live site (app/pricing.jsx).
    assert [get(i)["price"] for i in ("web-starter", "web-growth", "web-premium")] \
        == [300, 700, 1400], "website tiers must match clientforge.tech"
    assert [get(i)["price"] for i in ("auto-basic", "auto-growth", "auto-advanced")] \
        == [250, 550, 1100], "automation tiers must match clientforge.tech"
    assert [get(i)["price"] for i in ("ads-starter", "ads-growth", "ads-scale")] \
        == [250, 450, 750], "ads tiers must match clientforge.tech"

    # At least one recurring offer must exist — the care plan IS the business,
    # and the old sheet asserted the opposite, which is why it couldn't quote it.
    assert any(o["monthly"] for o in OFFERS), "the recurring offer is the business"
    assert all(o.get("ad_spend_separate") for o in OFFERS
               if o["service"] == "Ads Management"), "ad spend is never ours to bill"

    # Every offer must map to a real service tag, or the client record can't
    # record what they actually signed up for.
    for o in OFFERS:
        assert o["service"] in agency_io.SERVICES, f"{o['id']}: unknown service {o['service']}"

    std = normalize({"id": PRIMARY_ID})
    assert std["price"] == 129 and std["custom"] is False, std
    assert std["buildPrice"] == 0.0, std
    assert line(std) == "Website + Care Plan — $129/mo + free build", line(std)

    one_time = normalize({"id": "web-growth"})
    assert line(one_time) == "Growth Website — $700", line(one_time)

    cus = normalize({"custom": True, "name": " Starter bundle ", "price": "175",
                     "monthly": True, "includes": "site + 1 automation"})
    assert cus["price"] == 175 and cus["monthly"] and cus["name"] == "Starter bundle", cus
    assert normalize({"id": "nope"}) is None
    print("agency_offers: ok")
