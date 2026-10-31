"""Dashboard KPIs and chart series. One implementation, shared by the app and (Phase 4) the Excel parity test.

Definitions (README "KPI definitions"):
- Applications: every record whose status kind is not "wishlist".
- Active: current kind applied / interview / offer.
- Interviews: reached an interview- or offer-kind status at any point (current status or history).
- Offers: reached an offer-kind status at any point.
- Rejections: current kind "rejected".
- Responded: reached interview/offer, or currently rejected. Withdrawn/Ghosted alone don't count.
- Response / interview / offer rate: that count ÷ applications.
- Avg days to first response: date applied -> first status change that counts as a response,
  over responded applications whose applied date is not in the future.
- Follow-ups: next_follow_up on records that aren't closed (rejected/closed kinds); overdue = before
  today, due this week = today .. today+6.
"""

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .models import Application, StatusHistory

RESPONSE_KINDS = ("interview", "offer")
CLOSED_KINDS = ("rejected", "closed")
UNSPECIFIED = "Not specified"


@dataclass
class Filters:
    start: date | None = None  # inclusive, on date_applied
    end: date | None = None  # inclusive
    source: str | None = None
    location: str | None = None


def split_locations(location: str | None) -> list[str]:
    if not location:
        return [UNSPECIFIED]
    parts = [p.strip() for p in re.split(r"[,/;|]", location) if p.strip()]
    return list(dict.fromkeys(parts)) or [UNSPECIFIED]


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


@dataclass
class AppFacts:
    app: Application
    kind: str
    reached_interview: bool
    reached_offer: bool
    responded: bool
    first_response: date | None
    furthest: int  # index of the furthest pipeline status reached (-1 if none)


def facts_for(app: Application, hist: list[StatusHistory], kinds: dict[str, str], pipeline: list[str]) -> AppFacts:
    kind = kinds.get(app.status, "applied")
    seen = [h.to_status for h in hist] + [app.status]
    seen_kinds = {kinds.get(s) for s in seen}
    reached_interview = bool(seen_kinds & set(RESPONSE_KINDS))
    reached_offer = "offer" in seen_kinds
    responded = reached_interview or kind == "rejected"
    first_response = None
    if responded:
        for h in sorted(hist, key=lambda h: (h.changed_at, h.id or 0)):
            if kinds.get(h.to_status) in (*RESPONSE_KINDS, "rejected"):
                first_response = h.changed_at.date()
                break
    furthest = max((pipeline.index(s) for s in seen if s in pipeline), default=-1)
    return AppFacts(app, kind, reached_interview, reached_offer, responded, first_response, furthest)


def _rate(n: int, d: int) -> float | None:
    return round(n / d, 4) if d else None


def compute(
    apps: list[Application],
    history: list[StatusHistory],
    statuses: list[dict],
    today: date,
    filters: Filters | None = None,
) -> dict:
    f = filters or Filters()
    kinds = {s["name"]: s["kind"] for s in statuses}
    # Funnel stages: the pipeline in settings order, minus wishlist and closed states.
    pipeline = [s["name"] for s in statuses if s["kind"] not in ("wishlist", *CLOSED_KINDS)]
    hist_by_app: dict[int, list[StatusHistory]] = defaultdict(list)
    for h in history:
        hist_by_app[h.application_id].append(h)

    def matches_dims(a: Application) -> bool:
        if f.source and (a.source or UNSPECIFIED) != f.source:
            return False
        if f.location and f.location not in split_locations(a.location):
            return False
        return True

    def in_range(a: Application) -> bool:
        if f.start is None and f.end is None:
            return True
        d = a.date_applied
        return d is not None and (f.start is None or d >= f.start) and (f.end is None or d <= f.end)

    dims = [a for a in apps if matches_dims(a)]
    wishlist = [a for a in dims if kinds.get(a.status) == "wishlist"]
    all_apps = [facts_for(a, hist_by_app[a.id], kinds, pipeline) for a in dims if kinds.get(a.status) != "wishlist"]
    facts = [x for x in all_apps if in_range(x.app)]

    total = len(facts)
    interviews = sum(x.reached_interview for x in facts)
    offers = sum(x.reached_offer for x in facts)
    responded = sum(x.responded for x in facts)
    delays = [
        (x.first_response - x.app.date_applied).days
        for x in facts
        if x.first_response and x.app.date_applied and x.app.date_applied <= today and x.first_response >= x.app.date_applied
    ]
    this_week, this_month = week_start(today), today.replace(day=1)
    # Follow-ups and "this week/month" are about now, so they ignore the date-range filter.
    open_records = [a for a in dims if kinds.get(a.status) not in CLOSED_KINDS and a.next_follow_up]

    kpis = {
        "applications": total,
        "applications_this_week": sum(1 for x in all_apps if x.app.date_applied and this_week <= x.app.date_applied <= today),
        "applications_this_month": sum(1 for x in all_apps if x.app.date_applied and this_month <= x.app.date_applied <= today),
        "companies": len({x.app.company.lower() for x in facts}),
        "wishlist": len(wishlist),
        "active": sum(x.kind in ("applied", "interview", "offer") for x in facts),
        "awaiting_response": sum(x.kind == "applied" for x in facts),
        "interviews": interviews,
        "offers": offers,
        "rejections": sum(x.kind == "rejected" for x in facts),
        "responded": responded,
        "response_rate": _rate(responded, total),
        "interview_rate": _rate(interviews, total),
        "offer_rate": _rate(offers, total),
        "avg_days_to_response": round(sum(delays) / len(delays), 1) if delays else None,
        "follow_ups_overdue": sum(1 for a in open_records if a.next_follow_up < today),
        "follow_ups_due_this_week": sum(1 for a in open_records if today <= a.next_follow_up <= today + timedelta(days=6)),
        "future_dated": sum(1 for x in facts if x.app.date_applied and x.app.date_applied > today),
        "undated": sum(1 for x in facts if not x.app.date_applied),
    }

    return {
        "kpis": kpis,
        "weekly": _weekly(facts, today, f),
        "funnel": [{"status": s, "count": sum(1 for x in facts if x.furthest >= i)} for i, s in enumerate(pipeline)],
        "by_status": [
            {"status": s["name"], "kind": s["kind"], "count": n}
            for s in statuses if s["kind"] != "wishlist" and (n := sum(1 for x in facts if x.app.status == s["name"]))
        ] + [
            {"status": name, "kind": "applied", "count": n}
            for name, n in Counter(x.app.status for x in facts if x.app.status not in kinds).items()
        ],
        "by_source": _by_source(facts),
        "by_location": [
            {"location": loc, "applications": n}
            for loc, n in sorted(Counter(l for x in facts for l in split_locations(x.app.location)).items(), key=lambda kv: (-kv[1], kv[0]))
        ],
        "by_work_mode": [
            {"work_mode": m, "applications": n}
            for m, n in sorted(Counter(x.app.work_mode or UNSPECIFIED for x in facts).items(), key=lambda kv: (-kv[1], kv[0]))
        ],
        "options": {
            "sources": sorted({a.source or UNSPECIFIED for a in apps if kinds.get(a.status) != "wishlist"}),
            "locations": sorted({l for a in apps if kinds.get(a.status) != "wishlist" for l in split_locations(a.location)}),
        },
    }


def _weekly(facts: list[AppFacts], today: date, f: Filters) -> list[dict]:
    """Applications per ISO week (Monday start). Future-dated (flagged) and undated records are left out."""
    dated = [x for x in facts if x.app.date_applied and x.app.date_applied <= today]
    if not dated and f.start is None:
        return []
    first = week_start(f.start or min(x.app.date_applied for x in dated))
    last = week_start(min(f.end or today, today))
    counts = Counter(week_start(x.app.date_applied) for x in dated)
    responded = Counter(week_start(x.app.date_applied) for x in dated if x.responded)
    weeks, w = [], first
    while w <= last:
        weeks.append({"week": w.isoformat(), "applications": counts[w], "responded": responded[w]})
        w += timedelta(days=7)
    return weeks


def _by_source(facts: list[AppFacts]) -> list[dict]:
    groups: dict[str, list[AppFacts]] = defaultdict(list)
    for x in facts:
        groups[x.app.source or UNSPECIFIED].append(x)
    rows = [
        {"source": s, "applications": len(xs), "responded": (r := sum(x.responded for x in xs)), "response_rate": _rate(r, len(xs))}
        for s, xs in groups.items()
    ]
    return sorted(rows, key=lambda r: (-r["applications"], r["source"]))
