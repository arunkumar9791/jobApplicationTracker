from datetime import date, datetime
from pathlib import Path

from sqlmodel import select

from app import importer, kpis, services, spreadsheet
from app.constants import DEFAULT_STATUSES
from app.models import Application, StatusHistory

TODAY = date(2026, 10, 31)  # a Saturday; week starts Mon 26 Oct
FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "jobs_sheet.xlsx"

_ids = iter(range(1, 10_000))


def app(company="Acme", status="Applied", applied=date(2026, 10, 20), **kw) -> Application:
    return Application(id=next(_ids), company=company, status=status, date_applied=applied, **kw)


def h(a: Application, to: str, when: date, frm: str | None = None) -> StatusHistory:
    return StatusHistory(id=next(_ids), application_id=a.id, from_status=frm, to_status=to, changed_at=datetime.combine(when, datetime.min.time()))


def run(apps, history, **filters):
    return kpis.compute(apps, history, DEFAULT_STATUSES, TODAY, kpis.Filters(**filters))


def test_core_kpis_and_rates():
    a1 = app("A")                                      # applied, no response
    a2 = app("B", "Rejected")                          # rejected = responded
    a3 = app("C", "First Round")                       # interview
    a4 = app("D", "Ghosted")                           # ghosted: closed, not responded
    a5 = app("E", "Rejected")                          # interviewed, then rejected
    a6 = app("F", "Accepted")                          # offer reached
    w = app("W", "Wishlist", applied=None)
    hist = [
        h(a2, "Applied", date(2026, 10, 20)), h(a2, "Rejected", date(2026, 10, 24), "Applied"),
        h(a3, "Applied", date(2026, 10, 20)), h(a3, "Screening", date(2026, 10, 22), "Applied"), h(a3, "First Round", date(2026, 10, 25), "Screening"),
        h(a5, "Applied", date(2026, 10, 20)), h(a5, "Screening", date(2026, 10, 26), "Applied"), h(a5, "Rejected", date(2026, 10, 29), "Screening"),
        h(a6, "Applied", date(2026, 10, 20)), h(a6, "Offer", date(2026, 10, 30), "Applied"), h(a6, "Accepted", date(2026, 10, 31), "Offer"),
    ]
    k = run([a1, a2, a3, a4, a5, a6, w], hist)["kpis"]
    assert k["applications"] == 6 and k["wishlist"] == 1
    assert k["active"] == 3                            # A, C, F (Accepted is offer kind)
    assert k["interviews"] == 3                        # C, E (rejected after interview), F
    assert k["offers"] == 1 and k["rejections"] == 2
    assert k["responded"] == 4                         # B, C, E, F – not A or D
    assert k["response_rate"] == round(4 / 6, 4)
    assert k["interview_rate"] == 0.5 and k["offer_rate"] == round(1 / 6, 4)
    # First responses: B 4 days, C 2, E 6, F 10 -> 5.5
    assert k["avg_days_to_response"] == 5.5


def test_empty():
    k = run([], [])["kpis"]
    assert k["applications"] == 0 and k["response_rate"] is None and k["avg_days_to_response"] is None


def test_this_week_month_and_follow_ups():
    apps = [
        app("A", applied=date(2026, 10, 26)),          # Monday this week
        app("B", applied=date(2026, 10, 25)),          # Sunday last week, this month
        app("C", applied=date(2026, 9, 30)),           # last month
        app("D", applied=date(2027, 10, 23)),          # future (flagged) – not "this week"
        app("E", next_follow_up=date(2026, 10, 30)),   # overdue
        app("F", next_follow_up=date(2026, 11, 6)),    # due within 7 days
        app("G", next_follow_up=date(2026, 11, 7)),    # beyond
        app("H", "Rejected", next_follow_up=date(2026, 10, 1)),   # closed: ignored
    ]
    k = run(apps, [])["kpis"]
    assert k["applications_this_week"] == 1
    assert k["applications_this_month"] == 2 + 4       # A, B + E, F, G, H applied 20 Oct
    assert (k["follow_ups_overdue"], k["follow_ups_due_this_week"]) == (1, 1)
    assert k["future_dated"] == 1


def test_filters():
    apps = [
        app("A", source="LinkedIn", location="Bengaluru, Chennai", applied=date(2026, 10, 5)),
        app("B", source="Referral", location="Chennai", applied=date(2026, 10, 25)),
        app("C", source=None, location=None, applied=None),
    ]
    assert run(apps, [], source="LinkedIn")["kpis"]["applications"] == 1
    assert run(apps, [], location="Chennai")["kpis"]["applications"] == 2       # multi-city match
    assert run(apps, [], source=kpis.UNSPECIFIED)["kpis"]["applications"] == 1
    r = run(apps, [], start=date(2026, 10, 19), end=date(2026, 10, 31))
    assert r["kpis"]["applications"] == 1                                       # undated excluded from a range
    assert r["kpis"]["applications_this_month"] == 2                            # "now" KPIs ignore the range
    opts = run(apps, [])["options"]
    assert opts["locations"] == ["Bengaluru", "Chennai", kpis.UNSPECIFIED]


def test_charts():
    a = app("A", "First Round", applied=date(2026, 10, 12), source="LinkedIn", location="Bengaluru, Chennai", work_mode="Remote")
    b = app("B", applied=date(2026, 10, 27), source="LinkedIn", location="Chennai")
    c = app("C", "Rejected", applied=date(2026, 10, 28), source="Referral")
    d = app("D", applied=date(2028, 1, 1))  # future: excluded from weekly chart
    hist = [h(a, "Applied", date(2026, 10, 12)), h(a, "First Round", date(2026, 10, 14), "Applied"),
            h(c, "Applied", date(2026, 10, 28)), h(c, "Rejected", date(2026, 10, 30), "Applied")]
    r = run([a, b, c, d], hist)
    assert r["weekly"] == [
        {"week": "2026-10-12", "applications": 1, "responded": 1},
        {"week": "2026-10-19", "applications": 0, "responded": 0},
        {"week": "2026-10-26", "applications": 2, "responded": 1},
    ]
    funnel = {x["status"]: x["count"] for x in r["funnel"]}
    assert funnel["Applied"] == 4 and funnel["Screening"] == 1 and funnel["First Round"] == 1 and funnel["Second Round"] == 0
    assert "Wishlist" not in funnel and "Rejected" not in funnel
    assert r["by_source"][0] == {"source": "LinkedIn", "applications": 2, "responded": 1, "response_rate": 0.5}
    assert {x["location"]: x["applications"] for x in r["by_location"]} == {"Chennai": 2, "Bengaluru": 1, kpis.UNSPECIFIED: 2}
    assert {x["status"]: x["count"] for x in r["by_status"]} == {"Applied": 2, "First Round": 1, "Rejected": 1}
    assert r["by_work_mode"][0] == {"work_mode": kpis.UNSPECIFIED, "applications": 3}


def test_custom_status_counts_by_kind():
    statuses = DEFAULT_STATUSES + [{"name": "Take-home", "kind": "interview", "color": "violet"}]
    a = app("A", "Take-home")
    r = kpis.compute([a], [h(a, "Applied", date(2026, 10, 20)), h(a, "Take-home", date(2026, 10, 23), "Applied")], statuses, TODAY)
    assert r["kpis"]["interviews"] == 1 and r["kpis"]["avg_days_to_response"] == 3


def test_real_fixture(session):
    content = FIXTURE.read_bytes()
    grid = spreadsheet.read_sheet(content, FIXTURE.name)
    _, rows = importer.analyze(grid, importer.ImportOptions(token="t", mode="replace"), session, ["Jobs Sheet"], today=TODAY)
    importer.commit(rows, "replace", session)
    apps = list(session.exec(select(Application)))
    hist = list(session.exec(select(StatusHistory)))
    k = kpis.compute(apps, hist, services.get_settings(session)["statuses"], TODAY)["kpis"]
    assert (k["applications"], k["companies"], k["wishlist"]) == (16, 9, 128)
    assert (k["interviews"], k["offers"], k["rejections"], k["responded"]) == (1, 0, 3, 4)
    assert k["response_rate"] == 0.25                  # rejections count as responses
    assert k["active"] == 13 and k["awaiting_response"] == 12
    # EPAM 28->30 Oct (2 days), Capgemini 27->30 Oct (3 days); future-dated EY rejections are excluded.
    assert k["avg_days_to_response"] == 2.5
    assert (k["future_dated"], k["undated"]) == (3, 1)


def test_api(client):
    client.post("/api/applications", json={"company": "A", "source": "LinkedIn", "date_applied": "2026-10-20"})
    client.post("/api/applications", json={"company": "B", "source": "Referral", "date_applied": "2026-10-21", "status": "Rejected"})
    r = client.get("/api/dashboard").json()
    assert r["kpis"]["applications"] == 2 and r["kpis"]["response_rate"] == 0.5
    r = client.get("/api/dashboard", params={"source": "LinkedIn", "start": "2026-10-01", "end": "2026-10-31"}).json()
    assert r["kpis"]["applications"] == 1
