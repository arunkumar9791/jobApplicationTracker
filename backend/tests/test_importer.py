import io
from collections import Counter
from datetime import date, datetime
from pathlib import Path

import pytest
from openpyxl import Workbook
from sqlmodel import select

from app import importer, services, spreadsheet
from app.models import Application, ApplicationCreate, StatusHistory
from app.normalise import match_status, suggest

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "jobs_sheet.xlsx"
TODAY = date(2026, 10, 31)
HEADERS = ["Company Name", "Job Title/Role", "Job ID", "Date Applied", "Application Source", "Job Link",
           "Location / Work Mode", "Current Status", "Last Updated", "Next Follow-up Date"]


def xlsx(rows, title="Jobs", hyperlinks=None) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = title
    for r in rows:
        ws.append(r)
    for (r, c), url in (hyperlinks or {}).items():
        ws.cell(r, c).hyperlink = url
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def run(session, content, filename="t.xlsx", mode="replace", **opts):
    sheets = spreadsheet.sheet_names(content, filename)
    sheet = opts.pop("sheet", None) or sheets[0]
    grid = spreadsheet.read_sheet(content, filename, None if sheet == "CSV" else sheet)
    o = importer.ImportOptions(token="t", mode=mode, sheet=sheet, **opts)
    return importer.analyze(grid, o, session, sheets, today=TODAY)


def commit(session, content, **kw):
    mode = kw.get("mode", "replace")
    res, rows = run(session, content, **kw)
    return res, importer.commit(rows, mode, session)


# ---------- real fixture ----------

def test_fixture_counts_flags_and_suggestions(session):
    res, _ = run(session, FIXTURE.read_bytes())
    c = res["counts"]
    assert res["header_row"] == 1
    assert (c["applications"], c["companies"]) == (16, 9)
    # 129 company-only rows; the Atlassian one is a duplicate of a real Atlassian application.
    assert c["wishlist"] == 128 and c["skipped"] == 1
    future = {i["row"]: i["fix"]["value"] for i in res["issues"] if "future" in i["message"]}
    assert future == {4: "2026-10-23", 5: "2026-10-23", 6: "2026-10-23"}
    sugg = {(s["field"], s["source"]): s["target"] for s in res["suggestions"]}
    assert sugg == {
        ("source", "Copmay Site"): "Company Site",
        ("location", "Banglore"): "Bengaluru",
        ("location", "Bangalore"): "Bengaluru",
    }
    assert [d["id"] for d in res["duplicates"]] == ["wishlist|atlassian"]


def test_fixture_commit_values(session):
    _, summary = commit(session, FIXTURE.read_bytes())
    assert summary == {"added": 144, "updated": 0, "unchanged": 0, "skipped": 1, "flagged": 4}
    apps = session.exec(select(Application)).all()
    by_job = {a.job_id: a for a in apps if a.job_id}
    assert by_job["854617"].company == "LTM (Mindtree)"         # numeric 854617.0 -> text
    assert len(by_job["1745956"].job_link) > 500                # full hyperlink target, not truncated text
    assert by_job["64167"].source == "Company Site" and by_job["64167"].location == "Bengaluru"
    assert by_job["1752434"].status == "Rejected"               # "Rejected " trimmed
    assert by_job["1751085"].flags == ["date_applied:future"]
    phonepe = next(a for a in apps if a.company == "Phonepe")
    assert phonepe.last_updated == datetime(2026, 10, 23, 12, 46, 49)   # ISO timestamp
    epam = next(a for a in apps if a.contact_person == "Alex Example")
    assert epam.status == "First Round" and not epam.title.startswith("\n")
    assert sum(a.status == "Wishlist" for a in apps) == 128
    # First Round record gets Applied -> First Round history for response-time KPIs.
    hist = session.exec(select(StatusHistory).where(StatusHistory.application_id == epam.id)).all()
    assert [h.to_status for h in hist] == ["Applied", "First Round"]


def test_fixture_declined_suggestions_and_date_fix(session):
    res, _ = run(session, FIXTURE.read_bytes(), declined=["location|Banglore"], date_fixes={"6": "2026-10-23"},
                 keep_duplicates=["wishlist|atlassian"])
    rows = {r["row"]: r for r in res["rows"]}
    assert rows[14]["location"] == "Banglore" and rows[14]["source"] == "Company Site"
    assert rows[6]["date_applied"] == "2026-10-23" and rows[6]["flags"] == []
    assert res["counts"]["wishlist"] == 129


def test_fixture_reimport_merge_is_noop(session):
    content = FIXTURE.read_bytes()
    commit(session, content)
    res, summary = commit(session, content, mode="merge")
    assert summary["added"] == 0 and summary["updated"] == 0
    assert summary["unchanged"] == 144


# ---------- messy sheets ----------

def test_header_not_on_row_one_blank_rows_spaces_and_extra_columns(session):
    content = xlsx([
        ["My job hunt 2026"],
        [],
        ["  Company Name ", "Job Title/Role", "Date Applied", "Current Status", "Recruiter Rating", "Notes"],
        [None, None, None],
        ["  Acme  Corp ", "  Backend   Engineer ", "05-09-2025", "applied", "4/5", "Line one\nLine two"],
        [],
        ["Globex", None, None, None, None, None],
    ])
    res, rows = run(session, content)
    assert res["header_row"] == 3
    assert res["mapping"]["4"] == importer.APPEND_TO_NOTES       # unknown column kept in notes
    assert res["counts"]["blank"] == 2
    acme = next(r for r in rows if r.company == "Acme Corp")
    assert acme.data["title"] == "Backend Engineer" and acme.data["status"] == "Applied"
    assert acme.data["notes"] == "Line one\nLine two\nRecruiter Rating: 4/5"
    assert acme.flags == ["date_applied:old"]                    # > 1 year old
    globex = next(r for r in rows if r.company == "Globex")
    assert globex.data["status"] == "Wishlist" and globex.is_wishlist


def test_mixed_date_formats_never_month_first(session):
    content = xlsx([
        HEADERS[:4],
        ["A", "x", None, "03-04-2026"],                          # 3 April
        ["B", "x", None, "2026-10-23T12:46:49.575Z"],
        ["C", "x", None, 46317],                                  # Excel serial = 22 Oct 2026
        ["D", "x", None, datetime(2026, 10, 1)],                  # real Excel date cell
        ["E", "x", None, "sometime"],
    ])
    res, rows = run(session, content)
    by = {r.company: r for r in rows}
    assert by["A"].data["date_applied"] == date(2026, 4, 3)
    assert by["B"].data["date_applied"] == date(2026, 10, 23)
    assert by["C"].data["date_applied"] == date(2026, 10, 22)
    assert by["D"].data["date_applied"] == date(2026, 10, 1)
    assert by["E"].data["date_applied"] is None and by["E"].flags == ["date_applied:invalid"]
    assert "Original Date Applied: sometime" in by["E"].data["notes"]


def test_future_and_old_dates_flagged_not_accepted_silently(session):
    content = xlsx([HEADERS[:4], ["A", "x", None, "23-10-2027"], ["B", "x", None, "01-01-2024"]])
    res, rows = run(session, content)
    by = {r.company: r for r in rows}
    assert by["A"].flags == ["date_applied:future"]
    assert by["B"].flags == ["date_applied:old"]
    assert {i["row"] for i in res["issues"] if i["field"] == "date_applied"} == {2, 3}


def test_hyperlink_target_preferred_and_bad_links(session):
    content = xlsx(
        [HEADERS[:6], ["A", "x", None, None, None, "Apply here"], ["B", "x", None, None, None, "www.example.com/jobs/1"],
         ["C", "x", None, None, None, "see email"]],
        hyperlinks={(2, 6): "https://example.com/" + "q" * 600},
    )
    _, rows = run(session, content)
    by = {r.company: r for r in rows}
    assert by["A"].data["job_link"].startswith("https://example.com/") and len(by["A"].data["job_link"]) > 600
    assert by["B"].data["job_link"] == "https://www.example.com/jobs/1"
    assert by["C"].data["job_link"] is None and "Job link: see email" in by["C"].data["notes"]


def test_job_id_kept_as_text(session):
    content = xlsx([HEADERS[:3], ["A", "x", "000123"], ["B", "x", 854617.0]])
    _, rows = run(session, content)
    assert [r.data["job_id"] for r in rows] == ["000123", "854617"]


def test_unknown_and_aliased_status(session):
    content = xlsx([["Company Name", "Current Status"], ["A", "Interviewing"], ["B", "rejectd"], ["C", "On hold"], ["D", "OFFER"]])
    res, rows = run(session, content)
    by = {r.company: r for r in rows}
    assert {(s["source"], s["target"]) for s in res["suggestions"] if s["field"] == "status"} == {("Interviewing", "Screening"), ("rejectd", "Rejected")}
    assert by["A"].data["status"] == "Screening" and by["B"].data["status"] == "Rejected"
    assert by["D"].data["status"] == "Offer"                     # case-only: applied without asking
    assert by["C"].data["status"] == "Applied" and "Original status: On hold" in by["C"].data["notes"]
    res, rows = run(session, content, declined=["status|Interviewing"])
    assert next(r for r in rows if r.company == "A").data["status"] == "Applied"


def test_row_without_company_is_skipped_with_error(session):
    content = xlsx([HEADERS[:2], [None, "Orphan role"], ["A", "x"]])
    res, rows = run(session, content)
    assert res["counts"]["skipped"] == 1 and res["counts"]["errors"] == 1
    assert rows[0].action == "skip"


def test_work_mode_column_and_derivation(session):
    content = xlsx([["Company Name", "Location", "Work Mode"], ["A", "Pune", "WFH"], ["B", "Remote - India", None], ["C", "Pune", "Sometimes"]])
    res, rows = run(session, content)
    assert [r.data["work_mode"] for r in rows] == ["Remote", "Remote", None]


def test_csv_semicolon_and_cp1252(session):
    content = "Company Name;Job Title/Role;Date Applied\nCafé Ltd;Dev;22/10/2026\n".encode("cp1252")
    res, rows = run(session, content, filename="jobs.csv")
    assert rows[0].company == "Café Ltd" and rows[0].data["date_applied"] == date(2026, 10, 22)


def test_xls(session):
    import xlwt

    wb = xlwt.Workbook()
    ws = wb.add_sheet("Old")
    for c, h in enumerate(HEADERS[:4]):
        ws.write(0, c, h)
    ws.write(1, 0, "Initech")
    ws.write(1, 3, datetime(2026, 10, 20), xlwt.easyxf(num_format_str="DD-MM-YYYY"))
    buf = io.BytesIO()
    wb.save(buf)
    res, rows = run(session, buf.getvalue(), filename="old.xls")
    assert res["sheets"] == ["Old"] and rows[0].data["date_applied"] == date(2026, 10, 20)


def test_sheet_selection(session):
    wb = Workbook()
    wb.active.title = "Notes"
    wb.active.append(["nothing here"])
    ws = wb.create_sheet("Jobs")
    ws.append(["Company Name", "Job Title/Role"])
    ws.append(["Acme", "Dev"])
    buf = io.BytesIO()
    wb.save(buf)
    res, rows = run(session, buf.getvalue(), sheet="Jobs")
    assert res["sheets"] == ["Notes", "Jobs"] and rows[0].company == "Acme"


def test_manual_mapping_and_validation(session):
    content = xlsx([["Org", "Position", "When"], ["Acme", "Dev", "01-10-2026"]])
    with pytest.raises(services.ValidationError):
        run(session, content, header_row=1)                       # nothing maps to company
    res, rows = run(session, content, header_row=1, mapping={"0": "company", "1": "title", "2": "date_applied"})
    assert rows[0].data["title"] == "Dev" and rows[0].data["date_applied"] == date(2026, 10, 1)
    with pytest.raises(services.ValidationError):
        run(session, content, header_row=1, mapping={"0": "company", "1": "title", "2": "title"})


# ---------- normalisation ----------

def test_normalisation_suggestions():
    values = {
        "source": Counter({"Company Site": 12, "Copmay Site": 1, "linkedin": 2, "Naukri.com": 1}),
        "location": Counter({"Bengaluru": 7, "Banglore": 1, "Bangalore": 1, "Bangalore, chennai": 1, "Chenai": 1}),
        "company": Counter({"PhonePe": 2, "Phonepe": 1, "Atlassian": 1, "Atlasian": 1}),
    }
    got = {(s.field, s.source): (s.target, s.reason) for s in suggest(values, {"source": ["Company Site", "LinkedIn", "Naukri"]})}
    assert got[("source", "Copmay Site")] == ("Company Site", "typo")
    assert got[("source", "linkedin")] == ("LinkedIn", "case")
    assert got[("source", "Naukri.com")] == ("Naukri", "alias")
    assert got[("location", "Banglore")] == ("Bengaluru", "alias")
    assert got[("location", "Bangalore, chennai")][0] == "Bengaluru, Chennai"
    assert got[("location", "Chenai")] == ("Chennai", "typo")
    assert got[("company", "Phonepe")] == ("PhonePe", "case")
    assert ("company", "Atlasian") not in got                     # companies never fuzzy-merge
    assert ("source", "Company Site") not in got


def test_match_status():
    from app.constants import DEFAULT_STATUSES
    names = [s["name"] for s in DEFAULT_STATUSES]
    assert match_status(" first round ", names) == ("First Round", None)
    assert match_status("Offered", names) == ("Offer", "alias")
    assert match_status("Ghosted!", names) == ("Ghosted", "typo")
    assert match_status("Paused", names) == (None, None)


# ---------- duplicates ----------

def test_duplicate_detection_rules(session):
    content = xlsx([
        HEADERS[:4],
        ["EY", "DE-Java-Senior", "1752431", "20-10-2026"],
        ["EY", "DE-Java-Senior ", "1752434", "20-10-2026"],   # different Job ID -> not a duplicate
        ["Acme", "Dev", "J-1", "20-10-2026"],
        ["ACME", "Developer", "j-1", "21-10-2026"],            # same company + Job ID
        ["Globex", "Backend Engineer", None, "20-10-2026"],
        ["Globex", "backend  engineer", None, None],           # same company + title, no Job ID
        ["Globex", None, None, None],                          # wishlist row for an applied company
    ])
    res, rows = run(session, content)
    ids = {d["id"] for d in res["duplicates"]}
    assert ids == {"job|acme|j-1", "title|globex|backend engineer", "wishlist|globex"}
    assert sum(r.action == "merged" for r in rows) == 3
    acme = next(r for r in rows if r.action == "add" and r.data["job_id"].lower() == "j-1")   # most recent row wins
    assert acme.row == 5 and acme.data["company"] == "Acme" and acme.data["title"] == "Developer"
    res, rows = run(session, content, keep_duplicates=["job|acme|j-1"])
    assert sum(r.action == "merged" for r in rows) == 2


# ---------- merge mode ----------

def _seed(session, **kw):
    return services.create_application(session, ApplicationCreate(**kw))


def test_merge_updates_adds_and_logs_history(session):
    acme = _seed(session, company="Acme", title="Dev", job_id="J-1", date_applied=date(2026, 10, 1), notes="keep me")
    wish = _seed(session, company="Globex", status="Wishlist")
    content = xlsx([
        ["Company Name", "Job Title/Role", "Job ID", "Current Status", "Notes"],
        ["Acme", "Dev", "J-1", "Screening", None],                # update status, keep notes (blank doesn't clear)
        ["Globex", "Platform Engineer", None, "Applied", None],   # wishlist entry gets applied to
        ["Initech", "SRE", None, "Applied", None],                # new
    ])
    res, summary = commit(session, content, mode="merge")
    # Flagged: Globex and Initech have no applied date; Acme's blank date doesn't change its record.
    assert summary == {"added": 1, "updated": 2, "unchanged": 0, "skipped": 0, "flagged": 2}
    session.refresh(acme)
    session.refresh(wish)
    assert acme.status == "Screening" and acme.notes == "keep me"
    assert wish.status == "Applied" and wish.title == "Platform Engineer"
    hist = session.exec(select(StatusHistory).where(StatusHistory.application_id == acme.id)).all()
    assert [h.to_status for h in hist] == ["Applied", "Screening"]


def test_merge_suggests_fix_even_when_typo_already_in_database(session):
    _seed(session, company="Standard Chartered", title="Full Stack Developer", job_id="64167", source="Copmay Site", location="Banglore")
    content = xlsx([HEADERS[:7], ["Standard Chartered", "Full Stack Developer", "64167", None, "Copmay Site", None, "Banglore"]])
    res, summary = commit(session, content, mode="merge")
    assert {(s["source"], s["target"]) for s in res["suggestions"]} == {("Copmay Site", "Company Site"), ("Banglore", "Bengaluru")}
    assert summary["updated"] == 1
    app = session.exec(select(Application)).one()
    assert (app.source, app.location) == ("Company Site", "Bengaluru")


def test_merge_by_record_id_is_authoritative(session):
    a = _seed(session, company="Acme", title="Dev", notes="old note")
    content = xlsx([["ID", "Company Name", "Job Title/Role", "Notes"], [a.id, "Acme", "Senior Dev", None]])
    res, summary = commit(session, content, mode="merge")
    session.refresh(a)
    assert summary["updated"] == 1 and a.title == "Senior Dev" and a.notes is None


def test_replace_mode_removes_existing(session):
    _seed(session, company="Old Co")
    content = xlsx([["Company Name", "Job Title/Role"], ["New Co", "Dev"]])
    res, summary = commit(session, content, mode="replace")
    assert [a.company for a in session.exec(select(Application))] == ["New Co"]


# ---------- API ----------

def test_api_upload_analyze_commit(client):
    content = FIXTURE.read_bytes()
    up = client.post("/api/import/upload", files={"file": ("jobs.xlsx", content)}).json()
    assert up["sheets"] == [{"name": "Jobs Sheet", "rows": 146}]
    body = {"token": up["token"], "sheet": "Jobs Sheet", "mode": "replace"}
    res = client.post("/api/import/analyze", json=body).json()
    assert res["counts"]["applications"] == 16
    summary = client.post("/api/import/commit", json=body).json()
    assert summary["added"] == 144
    assert len(client.get("/api/applications").json()) == 144
    assert client.post("/api/import/analyze", json=body).status_code == 404   # token consumed


def test_api_rejects_bad_files(client):
    assert client.post("/api/import/upload", files={"file": ("x.pdf", b"%PDF")}).status_code == 422
    assert client.post("/api/import/upload", files={"file": ("x.xlsx", b"not a zip")}).status_code == 422
