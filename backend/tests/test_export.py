import io
import warnings
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from openpyxl import load_workbook
from sqlmodel import select

from app import exporter, importer, kpis, services, spreadsheet
from app.models import Application, ApplicationCreate, ApplicationUpdate, StatusHistory

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "jobs_sheet.xlsx"
TODAY = date.today()  # Excel's TODAY() is the real date, so the app side uses it too


def load_fixture(session):
    grid = spreadsheet.read_sheet(FIXTURE.read_bytes(), FIXTURE.name)
    _, rows = importer.analyze(grid, importer.ImportOptions(token="t", mode="replace"), session, ["Jobs Sheet"])
    importer.commit(rows, "replace", session)


def enrich(session):
    """Add records that exercise every KPI path: offers, interview-then-rejected, follow-ups, odd values."""
    def add(**kw):
        return services.create_application(session, ApplicationCreate(**kw))

    a = add(company="Initech", title="Staff Engineer", date_applied=TODAY - timedelta(days=10), source="Referral",
            location="Pune / Remote", work_mode="Remote", next_follow_up=TODAY - timedelta(days=2), job_id="00042",
            notes='Line one\n="not a formula"\nLine 3', salary_range="40-50 LPA")
    services.update_application(session, a, ApplicationUpdate(status="Screening"))
    services.update_application(session, a, ApplicationUpdate(status="Offer"))
    b = add(company="Globex", title="Backend Dev", date_applied=TODAY - timedelta(days=5), source="LinkedIn",
            next_follow_up=TODAY + timedelta(days=3))
    services.update_application(session, b, ApplicationUpdate(status="First Round"))
    services.update_application(session, b, ApplicationUpdate(status="Rejected"))
    add(company="Hooli", title="SRE", date_applied=TODAY - timedelta(days=3), source="Naukri", next_follow_up=TODAY + timedelta(days=6))
    c = add(company="Soylent", title="Data Engineer", date_applied=TODAY - timedelta(days=20), next_follow_up=TODAY - timedelta(days=9))
    services.update_application(session, c, ApplicationUpdate(status="Screening"))
    services.update_application(session, c, ApplicationUpdate(status="Ghosted"))   # closed: follow-up no longer counts
    add(company="Umbrella", status="Wishlist", next_follow_up=TODAY - timedelta(days=1))
    d = session.exec(select(Application).where(Application.job_id == "1751085")).one()
    services.update_application(session, d, ApplicationUpdate(flags=[]))  # a dismissed review flag must survive


def snapshot(session) -> tuple[list[dict], list[tuple]]:
    apps = [a.model_dump(mode="json") for a in session.exec(select(Application).order_by(Application.id))]
    hist = sorted((h.application_id, h.from_status or "", h.to_status, h.changed_at.isoformat()) for h in session.exec(select(StatusHistory)))
    return apps, hist


def export(session, extra_rows=20):
    apps = list(session.exec(select(Application)))
    hist = list(session.exec(select(StatusHistory)))
    return exporter.build_workbook(apps, hist, services.get_settings(session), extra_rows=extra_rows)


def reimport(session, content: bytes, mode: str, **opts):
    sheets = spreadsheet.sheet_names(content, "x.xlsx")
    grid = spreadsheet.read_sheet(content, "x.xlsx", "Applications")
    res, rows = importer.analyze(grid, importer.ImportOptions(token="t", mode=mode, sheet="Applications", **opts), session, sheets)
    history = importer.parse_history_sheet(spreadsheet.read_sheet(content, "x.xlsx", "Status History"))
    return res, importer.commit(rows, mode, session, history)


# ---------- KPI parity: app vs Excel formulas ----------

def evaluate(content: bytes, tmp_path) -> dict[str, object]:
    import formulas

    p = tmp_path / "export.xlsx"
    p.write_bytes(content)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        sol = formulas.ExcelModel().loads(str(p)).finish().calculate()
    out = {}
    for k, v in sol.items():
        key = str(k).upper()
        if "]DASHBOARD'!" in key:
            val = getattr(v, "value", v)
            out[key.split("!")[-1]] = val[0][0] if hasattr(val, "__getitem__") and not isinstance(val, str) else val
    return out


def test_kpi_parity_with_excel_formulas(session, tmp_path):
    load_fixture(session)
    enrich(session)
    content, cells = export(session)
    excel = evaluate(content, tmp_path)
    app = kpis.compute(list(session.exec(select(Application))), list(session.exec(select(StatusHistory))),
                       services.get_settings(session)["statuses"], TODAY)["kpis"]
    assert set(cells) <= set(app)
    mismatches = {}
    for key, cell in cells.items():
        got, want = excel[cell.replace("$", "")], app[key]
        got = None if got == "" else float(got)
        if want is None or got is None:
            ok = want is None and got is None
        else:
            ok = abs(got - want) < 0.051 if key == "avg_days_to_response" else abs(got - want) < 1e-4
        if not ok:
            mismatches[key] = (got, want)
    assert not mismatches, mismatches
    # Sanity: the enriched data really exercises the interesting paths.
    assert app["offers"] == 1 and app["follow_ups_overdue"] == 2 and app["follow_ups_due_this_week"] == 1
    assert app["interviews"] >= 4                                       # incl. rejected and ghosted after interviews


def test_kpi_parity_empty_database(session, tmp_path):
    content, cells = export(session)
    excel = evaluate(content, tmp_path)
    assert float(excel[cells["applications"].replace("$", "")]) == 0
    assert excel[cells["response_rate"].replace("$", "")] in ("", None)


# ---------- workbook structure ----------

def test_workbook_structure(session):
    load_fixture(session)
    enrich(session)
    content, _ = export(session, extra_rows=2000)
    wb = load_workbook(io.BytesIO(content))
    assert wb.sheetnames == ["Dashboard", "Applications", "Lists", "Status History"]
    assert wb.active.title == "Dashboard"
    assert wb["Lists"].sheet_state == "hidden"
    ws = wb["Applications"]
    assert "Applications" in ws.tables and ws.freeze_panes == "B2"
    headers = [c.value for c in ws[1]]
    assert headers[:15] == ["Company Name", "Job Title/Role", "Job ID", "Date Applied", "Application Source", "Job Link",
                            "Location / Work Mode", "Work Mode", "Current Status", "Last Updated", "Next Follow-up Date",
                            "Contact Person", "Contact Email/LinkedIn", "Salary Range", "Notes"]
    rows = {r[0].value + "|" + str(r[2].value): r for r in ws.iter_rows(min_row=2) if r[0].value}
    initech = rows["Initech|00042"]
    assert initech[2].data_type == "s"                                  # Job ID stays text
    assert isinstance(initech[3].value, datetime) and initech[3].number_format == "dd-mm-yyyy"
    assert initech[14].value.startswith("Line one\n=") and initech[14].data_type == "s"   # not turned into a formula
    ey = next(r for k, r in rows.items() if k.startswith("EY|1745956"))
    assert ey[5].hyperlink is not None and len(ey[5].hyperlink.target) > 500
    assert str(ey[15].value).startswith("=IF(A")                        # calculated columns are plain A1 formulas
    dv = {str(v.sqref): v for v in ws.data_validations.dataValidation}
    assert any(v.formula1 == "Lists!$A$2:$A$12" for v in dv.values())  # status dropdown
    assert any(v.formula1.startswith("Lists!$F$2") and not v.showErrorMessage for v in dv.values())  # source: free text allowed
    assert len(ws.conditional_formatting) >= 3
    assert ws.column_dimensions["Z"].hidden                             # record ID kept but out of the way
    assert {"KPI_applications", "KPI_response_rate"} <= set(wb.defined_names.keys())
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        charts = [n for n in z.namelist() if n.startswith("xl/charts/chart")]
        assert len(charts) == 7                                         # native Excel charts, not images
        assert not [n for n in z.namelist() if n.startswith("xl/media/")]
        table_xml = z.read("xl/tables/table1.xml").decode()
        assert "calculatedColumnFormula" in table_xml                   # Excel fills formulas into new rows


def test_dashboard_formulas_reference_applications_sheet(session):
    load_fixture(session)
    content, cells = export(session, extra_rows=2000)
    ws = load_workbook(io.BytesIO(content))["Dashboard"]
    f = ws[cells["applications"].replace("$", "")].value
    assert f.startswith("=COUNTIFS(Applications!$P$2:$P$2145")
    assert ws["B6"].value == "=KPI_applications"                       # tile reads the KPI table


# ---------- round trip ----------

def test_round_trip_replace_is_lossless(session):
    load_fixture(session)
    enrich(session)
    before = snapshot(session)
    content, _ = export(session)
    res, summary = reimport(session, content, "replace")
    assert res["suggestions"] and not any(s["approved"] for s in res["suggestions"])  # defaults change nothing
    assert summary["skipped"] == 0 and summary["added"] == len(before[0])
    after = snapshot(session)
    assert after[0] == before[0]
    assert after[1] == before[1]


def test_round_trip_merge_changes_nothing(session):
    load_fixture(session)
    enrich(session)
    before = snapshot(session)
    content, _ = export(session)
    _, summary = reimport(session, content, "merge")
    assert summary["added"] == 0 and summary["updated"] == 0 and summary["unchanged"] == len(before[0])
    assert snapshot(session) == before


def test_import_after_editing_in_excel(session):
    load_fixture(session)
    content, _ = export(session)
    wb = load_workbook(io.BytesIO(content))
    ws = wb["Applications"]
    col = {c.value: i for i, c in enumerate(ws[1])}
    target = next(r for r in ws.iter_rows(min_row=2) if r[col["Company Name"]].value == "Netflix")
    target[col["Current Status"]].value = "Screening"
    target[col["Notes"]].value = "Recruiter called"
    new_row = ws.max_row + 1
    ws.cell(new_row, col["Company Name"] + 1, "Wayne Enterprises")
    ws.cell(new_row, col["Job Title/Role"] + 1, "Platform Engineer")
    ws.cell(new_row, col["Current Status"] + 1, "Applied")
    buf = io.BytesIO()
    wb.save(buf)

    _, summary = reimport(session, buf.getvalue(), "merge")
    assert summary["added"] == 1 and summary["updated"] == 1
    netflix = session.exec(select(Application).where(Application.company == "Netflix")).one()
    assert netflix.status == "Screening" and netflix.notes == "Recruiter called"
    hist = session.exec(select(StatusHistory).where(StatusHistory.application_id == netflix.id).order_by(StatusHistory.changed_at)).all()
    assert [h.to_status for h in hist] == ["Applied", "Screening"]
    assert session.exec(select(Application).where(Application.company == "Wayne Enterprises")).one()


def test_derived_columns_are_ignored_on_import():
    headers = [c.header for c in exporter.COLUMNS]
    mapping = importer.suggest_mapping(headers)
    by_header = {h: mapping[str(i)] for i, h in enumerate(headers)}
    assert by_header["Status Kind"] is None and by_header["First Response Date"] is None
    assert by_header["ID"] == "id" and by_header["Review Flags"] == "flags" and by_header["Work Mode"] == "work_mode"
    assert importer.APPEND_TO_NOTES not in mapping.values()


# ---------- filtered view & API ----------

def test_view_export_csv_and_xlsx(session):
    load_fixture(session)
    apps = list(session.exec(select(Application).where(Application.company == "EY")))
    text = exporter.build_view(apps, ["company", "job_id", "date_applied", "status"], "csv").decode("utf-8-sig")
    lines = text.strip().splitlines()
    assert lines[0] == "Company Name,Job ID,Date Applied,Current Status"
    assert "EY,1745956,23-10-2026,Applied" in lines
    wb = load_workbook(io.BytesIO(exporter.build_view(apps, ["company", "job_link"], "xlsx")))
    ws = wb.active
    assert [c.value for c in ws[1]] == ["Company Name", "Job Link"] and ws.max_row == len(apps) + 1


def test_export_api(client):
    client.post("/api/applications", json={"company": "Acme", "date_applied": "2026-10-20"})
    r = client.get("/api/export/xlsx")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert load_workbook(io.BytesIO(r.content)).sheetnames[0] == "Dashboard"
    ids = [a["id"] for a in client.get("/api/applications").json()]
    r = client.post("/api/export/view", json={"ids": ids, "fields": ["company"], "format": "csv"})
    assert r.status_code == 200 and "Acme" in r.text
    assert client.post("/api/export/view", json={"ids": ids, "format": "pdf"}).status_code == 422


def test_api_reimport_uses_history_sheet(client):
    client.post("/api/applications", json={"company": "Acme", "date_applied": "2026-10-20"})
    a = client.get("/api/applications").json()[0]
    client.patch(f"/api/applications/{a['id']}", json={"status": "Screening"})
    content = client.get("/api/export/xlsx").content
    token = client.post("/api/import/upload", files={"file": ("export.xlsx", content)}).json()["token"]
    body = {"token": token, "mode": "replace"}
    res = client.post("/api/import/analyze", json=body).json()
    assert res["sheet"] == "Applications"                               # picked over Dashboard automatically
    client.post("/api/import/commit", json=body)
    hist = client.get(f"/api/applications/{a['id']}/history").json()
    assert [h["to_status"] for h in hist] == ["Applied", "Screening"]
