"""Excel export with XlsxWriter: native charts, live-formula KPIs, dropdowns, conditional formatting.

Workbook layout
- Dashboard: KPI tiles + native charts. Every number is a formula over the Applications sheet,
  so editing data in Excel (or Google Sheets) updates the dashboard.
- Applications: an Excel Table with the user's columns, then calculated columns (row-independent
  INDEX(..., ROW()) formulas, so they auto-fill for new table rows and work in Google Sheets),
  then hidden columns carrying status-history facts and record IDs for a lossless re-import.
- Lists (hidden): statuses + kinds, pipeline order, sources, work modes – feeds the dropdowns.
- Status History: every status change.

Formulas deliberately use plain A1 ranges (no structured references) for Google Sheets compatibility.
"""

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import xlsxwriter
from xlsxwriter.utility import xl_col_to_name, xl_rowcol_to_cell

from .constants import WORK_MODES
from .kpis import CLOSED_KINDS, UNSPECIFIED, facts_for, split_locations
from .models import Application, StatusHistory

DATE_FMT = "dd-mm-yyyy"
DATETIME_FMT = "dd-mm-yyyy hh:mm"
MAX_URL = 2079  # Excel's hyperlink length limit; longer links are written as plain text
BLUE = "#2A78D6"
WEEKS = 12


@dataclass(frozen=True)
class Col:
    header: str
    width: float
    key: str | None = None  # Application attribute, for data columns
    kind: str = "text"  # text | date | datetime | url | wrap
    group: str = "data"  # data | calc | hidden


COLUMNS: list[Col] = [
    Col("Company Name", 24, "company"),
    Col("Job Title/Role", 36, "title"),
    Col("Job ID", 12, "job_id"),
    Col("Date Applied", 13, "date_applied", "date"),
    Col("Application Source", 20, "source"),
    Col("Job Link", 30, "job_link", "url"),
    Col("Location / Work Mode", 24, "location"),
    Col("Work Mode", 12, "work_mode"),
    Col("Current Status", 16, "status"),
    Col("Last Updated", 17, "last_updated", "datetime"),
    Col("Next Follow-up Date", 13, "next_follow_up", "date"),
    Col("Contact Person", 20, "contact_person"),
    Col("Contact Email/LinkedIn", 28, "contact_info"),
    Col("Salary Range", 14, "salary_range"),
    Col("Notes", 40, "notes", "wrap"),
    # Calculated (formulas)
    Col("Status Kind", 12, group="calc"),
    Col("Interviewed", 11, group="calc"),
    Col("Offered", 9, group="calc"),
    Col("Responded", 11, group="calc"),
    Col("Days to Response", 10, group="calc"),
    Col("Stage #", 8, group="calc"),
    # Hidden: facts from the app's status history, and identity for re-import
    Col("Reached Interview (history)", 12, group="hidden"),
    Col("Reached Offer (history)", 12, group="hidden"),
    Col("First Response Date", 13, kind="date", group="hidden"),
    Col("Furthest Stage # (history)", 10, group="hidden"),
    Col("ID", 7, "id", group="hidden"),
    Col("Created At", 17, "created_at", "datetime", group="hidden"),
    Col("Review Flags", 24, group="hidden"),
]
# Headers the importer must ignore (they are derived, not data).
DERIVED_HEADERS = {c.header for c in COLUMNS if c.group == "calc"} | {
    "Reached Interview (history)", "Reached Offer (history)", "First Response Date", "Furthest Stage # (history)",
}
L = {c.header: xl_col_to_name(i) for i, c in enumerate(COLUMNS)}  # header -> column letter


def _calc_formulas(n_statuses: int, n_pipeline: int, ref) -> dict[str, str]:
    """Calculated-column formulas. `ref(header)` renders a same-row reference: plain A1 for cell formulas,
    or a structured reference for the table's calculated-column definition (which Excel uses to fill new rows)."""
    kind, company, status = ref("Status Kind"), ref("Company Name"), ref("Current Status")
    applied, first = ref("Date Applied"), ref("First Response Date")
    return {
        "Status Kind": f'=IF({company}="","",IFERROR(VLOOKUP({status},Lists!$A$2:$B${n_statuses + 1},2,FALSE),"applied"))',
        "Interviewed": f'=IF({kind}="","",IF(OR({kind}="interview",{kind}="offer",{ref("Reached Interview (history)")}="Yes"),1,0))',
        "Offered": f'=IF({kind}="","",IF(OR({kind}="offer",{ref("Reached Offer (history)")}="Yes"),1,0))',
        "Responded": f'=IF({kind}="","",IF(OR({ref("Interviewed")}=1,{kind}="rejected"),1,0))',
        "Days to Response": (
            f'=IF(OR({kind}="",{kind}="wishlist",{first}="",{applied}=""),"",'
            f'IF(AND({applied}<=TODAY(),{first}>={applied}),{first}-{applied},""))'
        ),
        "Stage #": f'=IF({kind}="","",MAX(IFERROR(MATCH({status},Lists!$D$2:$D${n_pipeline + 1},0),0),N({ref("Furthest Stage # (history)")})))',
    }


def _structured(header: str) -> str:
    return "[@[" + header.replace("'", "''").replace("#", "'#").replace("[", "'[").replace("]", "']") + "]]"


def _a1(row: int):
    return lambda header: f"{L[header]}{row + 1}"


class _Ranges:
    """Absolute ranges on the Applications sheet, sized to leave room for rows added in Excel."""

    def __init__(self, max_row: int):
        self.max_row = max_row

    def __call__(self, header: str) -> str:
        col = L[header]
        return f"Applications!${col}$2:${col}${self.max_row}"


APP_KINDS = ("applied", "interview", "offer", "rejected", "closed")  # every kind except wishlist
OPEN_KINDS = ("wishlist", "applied", "interview", "offer")  # not closed (follow-ups count here)


def _count_kinds(R: "_Ranges", kinds: tuple[str, ...], extra: str = "") -> str:
    """Sum of COUNTIFS per status kind. Counting kinds explicitly (rather than "<>wishlist" / "<>")
    behaves identically in Excel, Google Sheets and formula engines that treat blanks differently."""
    tail = f",{extra}" if extra else ""
    return "+".join(f'COUNTIFS({R("Status Kind")},"{k}"{tail})' for k in kinds)


def kpi_formulas(R: _Ranges) -> dict[str, str]:
    """KPI name -> formula. Keys match kpis.compute()['kpis'] so the parity test can compare them."""
    kind, applied, follow = R("Status Kind"), R("Date Applied"), R("Next Follow-up Date")
    week = f'{applied},">="&(TODAY()-WEEKDAY(TODAY(),2)+1),{applied},"<="&TODAY()'
    month = f'{applied},">="&DATE(YEAR(TODAY()),MONTH(TODAY()),1),{applied},"<="&TODAY()'
    return {
        "applications": "=" + _count_kinds(R, APP_KINDS),
        "applications_this_week": "=" + _count_kinds(R, APP_KINDS, week),
        "applications_this_month": "=" + _count_kinds(R, APP_KINDS, month),
        "active": "=" + _count_kinds(R, ("applied", "interview", "offer")),
        "awaiting_response": f'=COUNTIFS({kind},"applied")',
        "interviews": f'=SUM({R("Interviewed")})-SUMIFS({R("Interviewed")},{kind},"wishlist")',
        "offers": f'=SUM({R("Offered")})-SUMIFS({R("Offered")},{kind},"wishlist")',
        "rejections": f'=COUNTIFS({kind},"rejected")',
        "responded": f'=SUM({R("Responded")})-SUMIFS({R("Responded")},{kind},"wishlist")',
        "response_rate": '=IF(KPI_applications=0,"",KPI_responded/KPI_applications)',
        "interview_rate": '=IF(KPI_applications=0,"",KPI_interviews/KPI_applications)',
        "offer_rate": '=IF(KPI_applications=0,"",KPI_offers/KPI_applications)',
        "avg_days_to_response": f'=IFERROR(AVERAGE({R("Days to Response")}),"")',
        "follow_ups_overdue": "=" + _count_kinds(R, OPEN_KINDS, f'{follow},"<"&TODAY()'),
        "follow_ups_due_this_week": "=" + _count_kinds(R, OPEN_KINDS, f'{follow},">="&TODAY(),{follow},"<="&(TODAY()+6)'),
        "wishlist": f'=COUNTIFS({kind},"wishlist")',
    }


KPI_LABELS = {
    "applications": "Applications (excl. wishlist)",
    "applications_this_week": "Applied this week (Mon–today)",
    "applications_this_month": "Applied this month",
    "active": "Active (not closed)",
    "awaiting_response": "Awaiting first response",
    "interviews": "Interviews (reached Screening+)",
    "offers": "Offers",
    "rejections": "Rejections",
    "responded": "Responded (incl. rejections)",
    "response_rate": "Response rate",
    "interview_rate": "Interview rate",
    "offer_rate": "Offer rate",
    "avg_days_to_response": "Avg days to first response",
    "follow_ups_overdue": "Follow-ups overdue",
    "follow_ups_due_this_week": "Follow-ups due in next 7 days",
    "wishlist": "Wishlist companies",
}
PERCENT_KPIS = {"response_rate", "interview_rate", "offer_rate"}


def build_workbook(
    apps: list[Application],
    history: list[StatusHistory],
    settings: dict,
    *,
    today: date | None = None,
    extra_rows: int = 2000,
) -> tuple[bytes, dict[str, str]]:
    """Returns (xlsx bytes, KPI name -> Dashboard cell address)."""
    today = today or date.today()
    statuses = settings["statuses"]
    kinds = {s["name"]: s["kind"] for s in statuses}
    pipeline = [s["name"] for s in statuses if s["kind"] not in ("wishlist", *CLOSED_KINDS)]
    hist_by_app: dict[int, list[StatusHistory]] = {}
    for h in history:
        hist_by_app.setdefault(h.application_id, []).append(h)
    apps = sorted(apps, key=lambda a: a.id or 0)

    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True, "strings_to_numbers": False, "strings_to_urls": False, "strings_to_formulas": False})
    wb.set_properties({"title": "Job Application Tracker", "comments": "Exported by Job Application Tracker"})
    fmt = _formats(wb)

    dash = wb.add_worksheet("Dashboard")
    ws = wb.add_worksheet("Applications")
    lists = wb.add_worksheet("Lists")
    hist_ws = wb.add_worksheet("Status History")

    n = len(apps)
    max_row = max(n + 1 + extra_rows, 500)
    R = _Ranges(max_row)

    n_sources = _write_lists(lists, fmt, statuses, pipeline, settings["sources"], apps)
    _write_applications(wb, ws, fmt, apps, hist_by_app, kinds, pipeline, max_row, n_sources)
    _write_history(hist_ws, fmt, apps, history)
    cells = _write_dashboard(wb, dash, fmt, R, apps, kinds, statuses, pipeline, today)

    dash.activate()
    wb.close()
    return buf.getvalue(), cells


def _formats(wb) -> dict[str, Any]:
    base = {"font_name": "Calibri", "font_size": 11, "valign": "vcenter"}
    f = lambda **kw: wb.add_format({**base, **kw})  # noqa: E731
    return {
        "text": f(),
        "wrap": f(text_wrap=True, valign="top"),
        "date": f(num_format=DATE_FMT, align="left"),
        "datetime": f(num_format=DATETIME_FMT, align="left"),
        "url": f(font_color="#1D4ED8", underline=1),
        "calc_head": f(bold=True, bg_color="#E2E8F0", font_color="#334155", text_wrap=True, border=1, border_color="#CBD5E1"),
        "hidden_head": f(bold=True, bg_color="#F1F5F9", font_color="#64748B", text_wrap=True),
        "head": f(bold=True, font_color="#FFFFFF", bg_color="#4F46E5"),
        "title": f(bold=True, font_size=20, font_color="#0F172A"),
        "subtitle": f(font_color="#64748B"),
        "section": f(bold=True, font_size=13, font_color="#0F172A"),
        "tile_label": f(font_color="#64748B", bg_color="#F8FAFC", top=1, left=1, right=1, border_color="#E2E8F0", indent=1),
        "tile_value": f(bold=True, font_size=24, font_color="#0F172A", bg_color="#F8FAFC", left=1, right=1, border_color="#E2E8F0", align="left", indent=1),
        "tile_value_pct": f(bold=True, font_size=24, font_color="#0F172A", bg_color="#F8FAFC", left=1, right=1, border_color="#E2E8F0", align="left", indent=1, num_format="0%"),
        "tile_value_dec": f(bold=True, font_size=24, font_color="#0F172A", bg_color="#F8FAFC", left=1, right=1, border_color="#E2E8F0", align="left", indent=1, num_format="0.0"),
        "tile_sub": f(font_size=9, font_color="#64748B", bg_color="#F8FAFC", bottom=1, left=1, right=1, border_color="#E2E8F0", indent=1),
        "kpi_name": f(font_color="#334155"),
        "kpi_val": f(bold=True, align="right"),
        "kpi_pct": f(bold=True, align="right", num_format="0.0%"),
        "kpi_dec": f(bold=True, align="right", num_format="0.0"),
        "tbl_head": f(bold=True, font_color="#334155", bottom=1, border_color="#CBD5E1"),
        "week": f(num_format="dd mmm"),
        "pct": f(num_format="0%"),
        "note": f(font_size=9, font_color="#64748B", italic=True),
    }


# ---------- Lists ----------

def _write_lists(ws, fmt, statuses, pipeline, sources, apps) -> int:
    """Returns the number of sources written (for the dropdown range)."""
    for c, h in enumerate(["Status", "Kind", "", "Pipeline (funnel order)", "", "Sources", "", "Work Modes"]):
        if h:
            ws.write(0, c, h, fmt["head"])
    for i, s in enumerate(statuses, start=1):
        ws.write_string(i, 0, s["name"])
        ws.write_string(i, 1, s["kind"])
    for i, p in enumerate(pipeline, start=1):
        ws.write_string(i, 3, p)
    all_sources = list(dict.fromkeys(sources + sorted({a.source for a in apps if a.source})))
    for i, s in enumerate(all_sources, start=1):
        ws.write_string(i, 5, s)
    for i, m in enumerate(WORK_MODES, start=1):
        ws.write_string(i, 7, m)
    ws.set_column(0, 7, 22)
    ws.hide()
    return len(all_sources)


# ---------- Applications ----------

def _write_applications(wb, ws, fmt, apps, hist_by_app, kinds, pipeline, max_row, n_sources) -> None:
    n = len(apps)
    last_row = max(n, 1)
    calc = _calc_formulas(len(kinds), len(pipeline), _structured)
    ws.add_table(0, 0, last_row, len(COLUMNS) - 1, {
        "name": "Applications",
        "style": "Table Style Light 9",
        "columns": [{"header": c.header, **({"formula": calc[c.header]} if c.header in calc else {})} for c in COLUMNS],
    })
    for i, c in enumerate(COLUMNS):
        head = fmt["calc_head"] if c.group == "calc" else fmt["hidden_head"] if c.group == "hidden" else None
        if head:
            ws.write_string(0, i, c.header, head)
        opts = {"level": 1, "hidden": True} if c.group == "hidden" else {}
        ws.set_column(i, i, c.width, fmt[c.kind] if c.kind in ("date", "datetime", "wrap") else None, opts)
    ws.set_column(len(COLUMNS), len(COLUMNS), None, None, {"collapsed": True})
    ws.set_row(0, 32)
    ws.freeze_panes(1, 1)

    col_index = {c.header: i for i, c in enumerate(COLUMNS)}
    for r, a in enumerate(apps, start=1):
        hist = hist_by_app.get(a.id, [])
        facts = facts_for(a, hist, kinds, pipeline)
        hist_kinds = {kinds.get(h.to_status) for h in hist}
        hist_stage = max((pipeline.index(h.to_status) + 1 for h in hist if h.to_status in pipeline), default=0)
        for i, c in enumerate(COLUMNS):
            if c.key:
                _write_value(ws, fmt, r, i, c, getattr(a, c.key))
        ws.write_string(r, col_index["Reached Interview (history)"], "Yes" if hist_kinds & {"interview", "offer"} else "")
        ws.write_string(r, col_index["Reached Offer (history)"], "Yes" if "offer" in hist_kinds else "")
        if facts.first_response:
            ws.write_datetime(r, col_index["First Response Date"], facts.first_response, fmt["date"])
        ws.write_number(r, col_index["Furthest Stage # (history)"], hist_stage)
        ws.write_string(r, col_index["Review Flags"], ", ".join(a.flags))
    # Plain A1 cell formulas (the table keeps the structured version for auto-filling new rows).
    # Includes the placeholder row an empty table needs.
    for r in range(1, last_row + 1):
        for header, formula in _calc_formulas(len(kinds), len(pipeline), _a1(r)).items():
            ws.write_formula(r, col_index[header], formula)

    # Dropdowns (also cover empty rows below the data, for new entries).
    status_col, source_col, mode_col = col_index["Current Status"], col_index["Application Source"], col_index["Work Mode"]
    ws.data_validation(1, status_col, max_row - 1, status_col, {
        "validate": "list", "source": f"=Lists!$A$2:$A${len(kinds) + 1}",
        "error_title": "Unknown status", "error_message": "Pick a status from the list (edit the list in the app's settings).",
    })
    ws.data_validation(1, source_col, max_row - 1, source_col, {
        "validate": "list", "source": f"=Lists!$F$2:$F${n_sources + 1}", "show_error": False,
        "input_title": "Source", "input_message": "Pick from the list or type your own.",
    })
    ws.data_validation(1, mode_col, max_row - 1, mode_col, {"validate": "list", "source": f"=Lists!$H$2:$H${len(WORK_MODES) + 1}"})

    # Status colours by kind, future/odd applied dates, overdue follow-ups.
    kind_col = L["Status Kind"]
    colours = {"wishlist": ("#FEF3C7", "#92400E"), "applied": ("#DBEAFE", "#1E40AF"), "interview": ("#EDE9FE", "#5B21B6"),
               "offer": ("#D1FAE5", "#065F46"), "rejected": ("#FEE2E2", "#991B1B"), "closed": ("#F1F5F9", "#475569")}
    def cf(bg: str, fg: str, bold: bool = False):
        return wb.add_format({"bg_color": bg, "font_color": fg, "bold": bold})

    for k, (bg, fg) in colours.items():
        ws.conditional_format(1, status_col, max_row - 1, status_col, {
            "type": "formula", "criteria": f'=${kind_col}2="{k}"', "format": cf(bg, fg),
        })
    d, fu = L["Date Applied"], L["Next Follow-up Date"]
    ws.conditional_format(1, col_index["Date Applied"], max_row - 1, col_index["Date Applied"], {
        "type": "formula", "criteria": f'=AND(${d}2<>"",${d}2>TODAY())', "format": cf("#FEF3C7", "#92400E"),
    })
    ws.conditional_format(1, col_index["Next Follow-up Date"], max_row - 1, col_index["Next Follow-up Date"], {
        "type": "formula", "criteria": f'=AND(${fu}2<>"",${fu}2<TODAY(),${kind_col}2<>"rejected",${kind_col}2<>"closed")',
        "format": cf("#FEE2E2", "#B91C1C", bold=True),
    })


def _write_value(ws, fmt, r: int, c: int, col: Col, value) -> None:
    if value in (None, ""):
        return
    if col.kind == "date":
        ws.write_datetime(r, c, value, fmt["date"])
    elif col.kind == "datetime":
        ws.write_datetime(r, c, value, fmt["datetime"])
    elif col.kind == "url" and len(value) <= MAX_URL:
        ws.write_url(r, c, value, fmt["url"], string=value)
    elif isinstance(value, int) and not isinstance(value, bool):
        ws.write_number(r, c, value)
    else:
        ws.write_string(r, c, str(value), fmt["wrap"] if col.kind == "wrap" else None)


# ---------- Status History ----------

def _write_history(ws, fmt, apps, history) -> None:
    by_id = {a.id: a for a in apps}
    rows = sorted(history, key=lambda h: (h.application_id, h.changed_at, h.id or 0))
    headers = ["Application ID", "Company", "Job Title", "From Status", "To Status", "Changed At"]
    ws.add_table(0, 0, max(len(rows), 1), len(headers) - 1, {
        "name": "StatusHistory", "style": "Table Style Light 9", "columns": [{"header": h} for h in headers],
    })
    for r, h in enumerate(rows, start=1):
        a = by_id.get(h.application_id)
        ws.write_number(r, 0, h.application_id)
        ws.write_string(r, 1, a.company if a else "")
        ws.write_string(r, 2, (a.title or "") if a else "")
        if h.from_status:
            ws.write_string(r, 3, h.from_status)
        ws.write_string(r, 4, h.to_status)
        ws.write_datetime(r, 5, h.changed_at, fmt["datetime"])
    for c, w in enumerate([14, 24, 36, 16, 16, 18]):
        ws.set_column(c, c, w)
    ws.freeze_panes(1, 0)


# ---------- Dashboard ----------

def _write_dashboard(wb, ws, fmt, R: _Ranges, apps, kinds, statuses, pipeline, today) -> dict[str, str]:
    ws.hide_gridlines(2)
    ws.set_column("A:A", 2)
    for col in ("B", "D", "F"):
        ws.set_column(f"{col}:{col}", 30)
    for col in ("C", "E", "G"):
        ws.set_column(f"{col}:{col}", 2)
    ws.set_column("H:H", 4)
    ws.set_column("I:I", 34)
    ws.set_column("J:L", 14)

    ws.write("B2", "Job Application Tracker", fmt["title"])
    ws.write("B3", f"Exported {today:%d-%m-%Y}. Every number below is a live formula over the Applications sheet – edit data there and the dashboard updates.", fmt["subtitle"])
    ws.set_row(1, 30)

    # KPI table (column I:J) – the single source the tiles and the parity test read.
    ws.write("I5", "All KPIs (live formulas)", fmt["section"])
    formulas = kpi_formulas(R)
    cells: dict[str, str] = {}
    for i, (key, formula) in enumerate(formulas.items()):
        row = 5 + i
        ws.write_string(row, 8, KPI_LABELS[key], fmt["kpi_name"])
        style = fmt["kpi_pct"] if key in PERCENT_KPIS else fmt["kpi_dec"] if key == "avg_days_to_response" else fmt["kpi_val"]
        ws.write_formula(row, 9, formula, style)
        cell = xl_rowcol_to_cell(row, 9, row_abs=True, col_abs=True)
        cells[key] = cell
        wb.define_name(f"KPI_{key}", f"=Dashboard!{cell}")
    kpi_end = 5 + len(formulas)

    # Tiles: 3 x 3, each = label / value / sub-line rows.
    tiles = [
        ("Applications", "applications", '=KPI_applications_this_week&" this week · "&KPI_applications_this_month&" this month"'),
        ("Active", "active", '=KPI_awaiting_response&" awaiting reply"'),
        ("Response rate", "response_rate", '=KPI_responded&" of "&KPI_applications&" responded"'),
        ("Interviews", "interviews", '=IF(KPI_interview_rate="","–",TEXT(KPI_interview_rate,"0%"))&" interview rate"'),
        ("Offers", "offers", '=IF(KPI_offer_rate="","–",TEXT(KPI_offer_rate,"0%"))&" offer rate"'),
        ("Rejections", "rejections", '=IF(KPI_applications=0,"–",TEXT(KPI_rejections/KPI_applications,"0%"))&" of applications"'),
        ("Avg days to response", "avg_days_to_response", '="from applying to first reply"'),
        ("Follow-ups overdue", "follow_ups_overdue", '=KPI_follow_ups_due_this_week&" due in the next 7 days"'),
        ("Wishlist", "wishlist", '="companies to apply to"'),
    ]
    for t, (label, key, sub) in enumerate(tiles):
        row = 4 + (t // 3) * 4
        col = 1 + (t % 3) * 2
        ws.write_string(row, col, label, fmt["tile_label"])
        style = fmt["tile_value_pct"] if key in PERCENT_KPIS else fmt["tile_value_dec"] if key == "avg_days_to_response" else fmt["tile_value"]
        ws.write_formula(row + 1, col, f"=KPI_{key}", style)
        ws.write_formula(row + 2, col, sub, fmt["tile_sub"])
    for r in (5, 9, 13):
        ws.set_row(r, 36)

    # Chart data (live formulas), below the KPI table.
    kind, applied = R("Status Kind"), R("Date Applied")
    row = kpi_end + 2
    ws.write(row, 8, "Chart data (live formulas)", fmt["section"])
    row += 1
    blocks: dict[str, tuple[int, int]] = {}

    def block(name: str, headers: list[str], rows: list[list[tuple[str, Any]]]):
        nonlocal row
        ws.write_string(row, 8, name, fmt["tbl_head"])
        for j, h in enumerate(headers):
            ws.write_string(row, 9 + j, h, fmt["tbl_head"])
        start = row + 1
        for k, cells_ in enumerate(rows):
            for j, (kind_, v) in enumerate(cells_):
                c, rr = 8 + j, start + k
                if kind_ == "f":
                    ws.write_formula(rr, c, v)
                elif kind_ == "fw":
                    ws.write_formula(rr, c, v, fmt["week"])
                elif kind_ == "fp":
                    ws.write_formula(rr, c, v, fmt["pct"])
                else:
                    ws.write_string(rr, c, v)
        blocks[name] = (start, start + max(len(rows), 1) - 1)
        row = start + len(rows) + 1

    week_rows = []
    for i in range(WEEKS):
        wcell = f"$I${row + 2 + i}"  # 1-based address of this row's week-start cell
        week_rows.append([
            ("fw", f"=TODAY()-WEEKDAY(TODAY(),2)+1-7*{WEEKS - 1 - i}"),
            ("f", "=" + _count_kinds(R, APP_KINDS, f'{applied},">="&{wcell},{applied},"<"&({wcell}+7)')),
        ])
    block("Week starting", ["Applications"], week_rows)

    stage = R("Stage #")
    block("Stage reached", ["Applications"], [[("s", p), ("f", f'=COUNTIFS({stage},">={i + 1}")')] for i, p in enumerate(pipeline)])

    block("Current status", ["Applications"], [
        [("s", s["name"]), ("f", f'=COUNTIFS({R("Current Status")},"{_q(s["name"])}")')] for s in statuses if s["kind"] != "wishlist"
    ])

    app_rows = [a for a in apps if kinds.get(a.status) != "wishlist"]
    sources = sorted({a.source or UNSPECIFIED for a in app_rows}) or [UNSPECIFIED]
    src_rows = []
    for k, s in enumerate(sources):
        crit = '""' if s == UNSPECIFIED else f'"{_q(s)}"'
        r1 = row + 2 + k
        src_rows.append([
            ("s", s),
            ("f", "=" + _count_kinds(R, APP_KINDS, f"{R('Application Source')},{crit}")),
            ("f", f"=SUMIFS({R('Responded')},{R('Application Source')},{crit})-SUMIFS({R('Responded')},{R('Application Source')},{crit},{kind},\"wishlist\")"),
            ("fp", f'=IF(J{r1}=0,0,K{r1}/J{r1})'),
        ])
    block("Source", ["Applications", "Responded", "Response rate"], src_rows)

    cities = sorted({c for a in app_rows for c in split_locations(a.location)} - {UNSPECIFIED}) + [UNSPECIFIED]
    block("Location", ["Applications"], [
        [("s", c), ("f", "=" + _count_kinds(R, APP_KINDS, f'{R("Location / Work Mode")},{chr(34) * 2 if c == UNSPECIFIED else chr(34) + "*" + _q(c) + "*" + chr(34)}'))]
        for c in cities
    ])
    block("Work mode", ["Applications"], [
        [("s", m), ("f", "=" + _count_kinds(R, APP_KINDS, f'{R("Work Mode")},{chr(34) * 2 if m == UNSPECIFIED else chr(34) + m + chr(34)}'))]
        for m in [*WORK_MODES, UNSPECIFIED]
    ])

    # Native charts.
    def series_ref(name: str, col: str) -> str:
        s, e = blocks[name]
        return f"=Dashboard!${col}${s + 1}:${col}${e + 1}"

    def chart(kind_: str, title: str, block_name: str, value_col: str = "J", pct: bool = False):
        ch = wb.add_chart({"type": kind_})
        ch.add_series({
            "name": title,
            "categories": series_ref(block_name, "I"),
            "values": series_ref(block_name, value_col),
            "fill": {"color": BLUE},
            "border": {"none": True},
            "gap": 60,
            "data_labels": {"value": True, "num_format": "0%" if pct else "0", "font": {"color": "#475569", "size": 9}},
        })
        ch.set_title({"name": title, "name_font": {"size": 12, "bold": True, "color": "#0F172A"}})
        ch.set_legend({"none": True})
        axis_font = {"color": "#64748B", "size": 9}
        value_axis = {"major_gridlines": {"visible": True, "line": {"color": "#E2E8F0"}}, "num_font": axis_font, "line": {"none": True}, "min": 0}
        if pct:
            value_axis.update({"num_format": "0%", "max": 1})
        cat_axis = {"num_font": axis_font, "line": {"color": "#CBD5E1"}}
        if kind_ == "bar":
            ch.set_x_axis(value_axis)
            ch.set_y_axis({**cat_axis, "reverse": True})
        else:
            ch.set_y_axis(value_axis)
            ch.set_x_axis({**cat_axis, "num_format": "dd mmm"} if block_name == "Week starting" else cat_axis)
        ch.set_chartarea({"border": {"color": "#E2E8F0"}})
        ch.set_size({"width": 520, "height": 300})
        return ch

    top = 17
    ws.write(top - 1, 1, "Charts", fmt["section"])
    ws.insert_chart(top, 1, chart("column", f"Applications per week (last {WEEKS})", "Week starting"), {"x_offset": 0, "y_offset": 4})
    ws.insert_chart(top, 4, chart("bar", "Pipeline funnel – reached each stage", "Stage reached"), {"x_offset": 20, "y_offset": 4})
    ws.insert_chart(top + 16, 1, chart("bar", "Applications by source", "Source"), {"y_offset": 4})
    ws.insert_chart(top + 16, 4, chart("bar", "Response rate by source", "Source", "L", pct=True), {"x_offset": 20, "y_offset": 4})
    ws.insert_chart(top + 32, 1, chart("bar", "Current status", "Current status"), {"y_offset": 4})
    ws.insert_chart(top + 32, 4, chart("bar", "By location", "Location"), {"x_offset": 20, "y_offset": 4})
    ws.insert_chart(top + 48, 1, chart("bar", "By work mode", "Work mode"), {"y_offset": 4})
    ws.write(top + 64, 1, "Multi-city roles count once per city. Charts read the 'Chart data' tables to the right.", fmt["note"])
    return cells


def _q(s: str) -> str:
    """Escape for a string literal inside a formula."""
    return s.replace('"', '""')


# ---------- filtered view ----------

VIEW_FIELDS = {c.key: c for c in COLUMNS if c.key and c.group == "data"}


def build_view(apps: list[Application], fields: list[str], fmt_: str) -> bytes:
    """The currently filtered table as CSV or a plain formatted .xlsx (no dashboard)."""
    cols = [VIEW_FIELDS[f] for f in fields if f in VIEW_FIELDS] or list(VIEW_FIELDS.values())
    if fmt_ == "csv":
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow([c.header for c in cols])
        for a in apps:
            w.writerow([_csv_value(getattr(a, c.key)) for c in cols])
        return ("﻿" + out.getvalue()).encode("utf-8")  # BOM so Excel opens UTF-8 correctly

    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True, "strings_to_numbers": False, "strings_to_urls": False, "strings_to_formulas": False})
    fmt = _formats(wb)
    ws = wb.add_worksheet("Applications")
    ws.add_table(0, 0, max(len(apps), 1), len(cols) - 1, {"name": "Applications", "style": "Table Style Light 9", "columns": [{"header": c.header} for c in cols]})
    for i, c in enumerate(cols):
        ws.set_column(i, i, c.width)
    for r, a in enumerate(apps, start=1):
        for i, c in enumerate(cols):
            _write_value(ws, fmt, r, i, c, getattr(a, c.key))
    ws.freeze_panes(1, 1)
    wb.close()
    return buf.getvalue()


def _csv_value(v) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.strftime("%d-%m-%Y %H:%M")
    if isinstance(v, date):
        return v.strftime("%d-%m-%Y")
    return str(v)
