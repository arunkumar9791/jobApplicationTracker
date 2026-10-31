"""Spreadsheet import: header detection, column mapping, row parsing, normalisation, duplicates, merge plan.

analyze() is a pure function of (grid, options, current database) and is re-run on every change in the
wizard; commit() re-runs it and writes the result, so the preview always matches what gets imported.
"""

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ValidationError
from sqlmodel import Session, delete, select

from . import services
from .constants import WORK_MODES
from .exporter import DERIVED_HEADERS
from .models import Application, ApplicationCreate, StatusHistory, now
from .normalise import NORMALISED_FIELDS, Suggestion, clean_vocab, match_status, match_work_mode, suggest
from .parsing import clean_text, date_flag, parse_date, parse_datetime
from .spreadsheet import Cell, Grid, cell_text

# field -> (label, header aliases). Aliases are compared after lowercasing and removing non-alphanumerics.
FIELDS: dict[str, tuple[str, list[str]]] = {
    "company": ("Company Name", ["company name", "company", "employer", "organisation", "organization", "company/organisation"]),
    "title": ("Job Title/Role", ["job title/role", "job title", "title", "role", "position", "designation", "job role"]),
    "job_id": ("Job ID", ["job id", "requisition id", "req id", "job code", "job ref", "reference id"]),
    "date_applied": ("Date Applied", ["date applied", "applied on", "applied date", "application date", "date of application"]),
    "source": ("Application Source", ["application source", "source", "channel", "applied via", "platform"]),
    "job_link": ("Job Link", ["job link", "link", "url", "job url", "posting url", "job posting"]),
    "location": ("Location / Work Mode", ["location / work mode", "location", "city", "job location"]),
    "work_mode": ("Work Mode", ["work mode", "work type", "remote/onsite", "workplace type"]),
    "status": ("Current Status", ["current status", "status", "application status"]),
    "last_updated": ("Last Updated", ["last updated", "updated", "last update", "updated on", "last modified"]),
    "next_follow_up": ("Next Follow-up Date", ["next follow-up date", "follow-up date", "next follow up", "follow up date", "follow-up", "follow up"]),
    "contact_person": ("Contact Person", ["contact person", "contact", "recruiter", "contact name", "hr name"]),
    "contact_info": ("Contact Email/LinkedIn", ["contact email/linkedin", "contact email", "email", "contact info", "linkedin profile"]),
    "interview_stage": ("Interview Stage", ["interview stage", "round"]),
    "salary_range": ("Salary Range", ["salary range", "salary", "ctc", "compensation", "expected ctc"]),
    "notes": ("Notes", ["notes", "comments", "remarks", "note"]),
    "id": ("Record ID (from this app)", ["id", "record id", "tracker id"]),
    "created_at": ("Created At", ["created at", "created", "date added"]),
    "flags": ("Review Flags (from this app)", ["review flags"]),
}
APPEND_TO_NOTES = "__notes__"
DATE_FIELDS = ("date_applied", "next_follow_up")
HEADER_SCAN_ROWS = 30
MAX_PREVIEW_SAMPLES = 3

# Fields whose presence (besides company) means "this is a real application, not a wishlist entry".
APPLICATION_SIGNALS = ("title", "job_id", "date_applied", "source", "job_link", "status")


def _hkey(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


_ALIAS_INDEX = {_hkey(a): f for f, (_, aliases) in FIELDS.items() for a in aliases}
_DERIVED = {_hkey(h) for h in DERIVED_HEADERS}  # calculated columns in our own exports: ignore, don't append to notes


def _ckey(company: str) -> str:
    return re.sub(r"[^a-z0-9]", "", company.lower())


def _tkey(title: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", title.lower()).split())


# ---------- options & result types ----------

class ImportOptions(BaseModel):
    token: str
    sheet: str | None = None
    header_row: int | None = None  # 1-based; None = auto-detect
    mapping: dict[str, str | None] | None = None  # column index -> field / "__notes__" / None (ignore)
    mode: Literal["replace", "merge"] = "merge"
    # None = defaults: approve every suggestion and merge every duplicate group – except for files exported
    # by this app (they carry record IDs), where defaults are "change nothing" so a round trip is lossless.
    declined: list[str] | None = None  # suggestion keys ("field|value") the user rejected
    keep_duplicates: list[str] | None = None  # duplicate group ids to keep as separate records
    date_fixes: dict[str, str] = {}  # sheet row number -> ISO date for Date Applied


@dataclass
class Issue:
    row: int
    company: str | None
    field: str | None
    level: Literal["error", "warning"]
    message: str
    fix: dict | None = None


@dataclass
class Row:
    row: int
    company: str | None
    data: dict[str, Any] = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)
    last_updated: datetime | None = None
    created_at: datetime | None = None
    record_id: int | None = None
    is_wishlist: bool = False
    skip: str | None = None
    action: str = "add"  # add | update | unchanged | skip | merged
    target_id: int | None = None
    changes: dict[str, Any] = field(default_factory=dict)
    note: str | None = None


# ---------- header detection & mapping ----------

def detect_header(grid: Grid) -> int:
    """0-based index of the row that best matches known headers (needs at least 2 matches)."""
    best, best_score = 0, 0
    for i, row in enumerate(grid[:HEADER_SCAN_ROWS]):
        score = len({_ALIAS_INDEX[k] for c in row if (k := _hkey(cell_text(c.value))) in _ALIAS_INDEX})
        if score > best_score:
            best, best_score = i, score
    return best if best_score >= 2 else 0


def suggest_mapping(headers: list[str]) -> dict[str, str | None]:
    mapping: dict[str, str | None] = {}
    used: set[str] = set()
    for i, h in enumerate(headers):
        f = _ALIAS_INDEX.get(_hkey(h))
        if _hkey(h) in _DERIVED:
            mapping[str(i)] = None
        elif f and f not in used:
            mapping[str(i)] = f
            used.add(f)
        else:
            # Unknown non-empty columns default to being kept in notes, so nothing is silently lost.
            mapping[str(i)] = APPEND_TO_NOTES if h.strip() else None
    return mapping


# ---------- parsing ----------

def _is_blank(cells: list[Cell]) -> bool:
    return all(cell_text(c.value) == "" and not c.link for c in cells)


def _collect_values(grid: Grid, header_idx: int, mapping: dict[str, str | None]) -> dict[str, Counter]:
    cols = {f: int(i) for i, f in mapping.items() if f in (*NORMALISED_FIELDS, "status")}
    counts: dict[str, Counter] = {f: Counter() for f in cols}
    for cells in grid[header_idx + 1:]:
        for f, i in cols.items():
            if i < len(cells) and (v := clean_text(cells[i].value)):
                counts[f][v] += 1
    return counts


def _suggest_year_fix(d: date, today: date) -> date | None:
    for year in (today.year, today.year - 1):
        try:
            candidate = d.replace(year=year)
        except ValueError:  # 29 Feb
            continue
        if candidate <= today:
            return candidate
    return None


def parse_row(
    cells: list[Cell], row_no: int, headers: list[str], mapping: dict[str, str | None],
    norm: dict[tuple[str, str], str], statuses: dict[str, str], date_fix: str | None, today: date,
) -> tuple[Row, list[Issue]]:
    raw: dict[str, Cell] = {}
    extra_notes: list[str] = []
    for i_str, target in mapping.items():
        i = int(i_str)
        if not target or i >= len(cells):
            continue
        if target == APPEND_TO_NOTES:
            if text := cell_text(cells[i].value):
                extra_notes.append(f"{headers[i] or f'Column {i + 1}'}: {text}")
        else:
            raw[target] = cells[i]

    issues: list[Issue] = []
    notes_extra: list[str] = []

    def text(f: str) -> str | None:
        c = raw.get(f)
        v = clean_text(c.value) if c else None
        if v and f in NORMALISED_FIELDS:
            v = norm.get((f, v), v)
        return v

    company = text("company")
    row = Row(row=row_no, company=company)

    def issue(f: str | None, level: Literal["error", "warning"], msg: str, fix: dict | None = None):
        issues.append(Issue(row_no, company, f, level, msg, fix))

    if not company:
        row.skip, row.action = "No company name", "skip"
        issue("company", "error", "No company name – row skipped")
        return row, issues

    # Status (blank = Wishlist when the row only names a company).
    raw_status = text("status")
    has_signals = any(text(f) for f in APPLICATION_SIGNALS if f != "status") or (raw.get("job_link") and raw["job_link"].link)
    if not raw_status:
        status = "Applied" if has_signals else "Wishlist"
    else:
        status = norm.get(("status", raw_status))
        if status is None:
            exact, reason = match_status(raw_status, list(statuses))
            status = exact if exact and reason is None else None
        if status is None:
            status = "Applied"
            notes_extra.append(f"Original status: {raw_status}")
            issue("status", "warning", f"Unknown status '{raw_status}' – imported as Applied")
    row.is_wishlist = statuses.get(status) == "wishlist"

    data: dict[str, Any] = {"company": company, "status": status}
    for f in ("title", "source", "location", "contact_person", "contact_info", "salary_range"):
        data[f] = text(f)
    data["job_id"] = text("job_id")

    # Job link: prefer the real hyperlink target over the display text.
    if link_cell := raw.get("job_link"):
        link = link_cell.link or clean_text(link_cell.value)
        if link and not re.match(r"^https?://", link, re.I):
            if re.match(r"^(www\.)?[\w-]+(\.[\w-]+)+(/\S*)?$", link):
                issue("job_link", "warning", f"Link '{link[:40]}' had no http(s):// – added https://")
                link = "https://" + link
            else:
                notes_extra.append(f"Job link: {link}")
                issue("job_link", "warning", "Job link is not a URL – moved to notes")
                link = None
        data["job_link"] = link

    # Work mode: explicit column, else derived from location text.
    wm = text("work_mode")
    if wm:
        wm = match_work_mode(wm) or (wm if wm in WORK_MODES else None)
        if wm is None:
            notes_extra.append(f"Work mode: {text('work_mode')}")
            issue("work_mode", "warning", f"Unknown work mode '{text('work_mode')}' – moved to notes")
    elif data["location"]:
        loc = data["location"].lower()
        wm = next((m for m in ("Remote", "Hybrid") if m.lower() in loc), None)
    data["work_mode"] = wm

    # Dates.
    for f in DATE_FIELDS:
        c = raw.get(f)
        try:
            data[f] = parse_date(c.value) if c else None
        except ValueError:
            data[f] = None
            row.flags.append(f"{f}:invalid")
            notes_extra.append(f"Original {FIELDS[f][0]}: {cell_text(c.value)}")
            issue(f, "warning", f"Couldn't read date '{cell_text(c.value)}' – left blank")
    if date_fix:
        data["date_applied"] = date.fromisoformat(date_fix)
    d = data["date_applied"]
    if not row.is_wishlist:
        if flag := date_flag(d, today):
            row.flags.append(f"date_applied:{flag}")
            if flag == "future":
                fixed = _suggest_year_fix(d, today)
                fix = {"type": "date", "value": fixed.isoformat(), "label": f"Use {fixed:%d-%m-%Y}"} if fixed else None
                issue("date_applied", "warning", f"Date applied {d:%d-%m-%Y} is in the future", fix)
            else:
                issue("date_applied", "warning", f"Date applied {d:%d-%m-%Y} is more than a year ago")
        elif d is None and "date_applied:invalid" not in row.flags:
            row.flags.append("date_applied:missing")
            issue("date_applied", "warning", "No date applied")

    if c := raw.get("last_updated"):
        try:
            row.last_updated = parse_datetime(c.value)
        except ValueError:
            issue("last_updated", "warning", f"Couldn't read Last Updated '{cell_text(c.value)}' – ignored")
    if row.last_updated and row.last_updated > now():
        row.last_updated = now()
    if row.last_updated is None and d and d <= today:
        row.last_updated = datetime.combine(d, datetime.min.time())
    if c := raw.get("created_at"):
        try:
            row.created_at = parse_datetime(c.value)
        except ValueError:
            pass
    if c := raw.get("id"):
        try:
            row.record_id = int(float(c.value)) if c.value not in (None, "") else None
        except (TypeError, ValueError):
            issue("id", "warning", f"Ignored non-numeric ID '{cell_text(c.value)}'")
    if "flags" in raw:
        # Our own export carries the record's review flags (including ones the user dismissed).
        text_flags = cell_text(raw["flags"].value)
        row.flags = [f.strip() for f in text_flags.split(",") if f.strip()]

    # Notes: the notes column, then anything folded in (interview stage, unmapped columns, originals).
    notes = None
    if (notes_cell := raw.get("notes")) is not None:
        # Keep line breaks in notes; only trim the ends.
        v = notes_cell.value
        notes = (v.strip() if isinstance(v, str) else clean_text(v)) or None
    if stage := text("interview_stage"):
        notes_extra.insert(0, f"Interview stage: {stage}")
    folded = notes_extra + extra_notes
    data["notes"] = "\n".join([notes] + folded if notes else folded) or None

    try:
        row.data = ApplicationCreate.model_validate(data).model_dump()
    except ValidationError as e:
        row.skip, row.action = "Invalid values", "skip"
        for err in e.errors():
            issue(str(err["loc"][0]) if err["loc"] else None, "error", f"{err['msg'].removeprefix('Value error, ')} – row skipped")
    return row, issues


# ---------- duplicates ----------

@dataclass
class DupGroup:
    id: str
    kind: Literal["same_job", "wishlist"]
    label: str
    rows: list[int]
    keep: bool = False


def _row_key(r: Row) -> tuple[str, ...]:
    ck = _ckey(r.data["company"])
    if r.data.get("job_id"):
        return ("job", ck, r.data["job_id"].lower())
    if r.data.get("title"):
        return ("title", ck, _tkey(r.data["title"]))
    return ("bare", ck)


def find_duplicates(rows: list[Row], keep: set[str]) -> list[DupGroup]:
    """Group likely duplicates and mark merged rows (action='merged') unless the user chose to keep both."""
    live = [r for r in rows if not r.skip]
    by_key: dict[tuple, list[Row]] = {}
    for r in live:
        by_key.setdefault(_row_key(r), []).append(r)
    applied_companies: dict[str, list[Row]] = {}
    for k, rs in by_key.items():
        if k[0] != "bare":
            applied_companies.setdefault(k[1], rs)

    groups: list[DupGroup] = []
    for key, members in by_key.items():
        company = members[0].data["company"]
        if len(members) > 1:
            what = f"Job ID {members[0].data['job_id']}" if key[0] == "job" else (members[0].data.get("title") or "no role")
            g = DupGroup("|".join(key), "same_job", f"{company} – {what} appears {len(members)} times", [m.row for m in members])
            g.keep = g.id in keep
            groups.append(g)
            if not g.keep:
                _merge_rows(members)
        if key[0] == "bare" and key[1] in applied_companies:
            target = applied_companies[key[1]][0]
            g = DupGroup(f"wishlist|{key[1]}", "wishlist",
                         f"{company} is on the wishlist but already has an application", [m.row for m in members] + [target.row])
            g.keep = g.id in keep
            groups.append(g)
            if not g.keep:
                for m in members:
                    if m.action != "merged":
                        m.action, m.note = "merged", f"Already applied (row {target.row})"
    return groups


def _merge_rows(members: list[Row]) -> None:
    """Keep the most recently updated row; fill its blanks from the others."""
    primary = max(members, key=lambda r: (r.last_updated or datetime.min, r.data.get("date_applied") or date.min, r.row))
    for other in members:
        if other is primary:
            continue
        for f, v in other.data.items():
            if v not in (None, "") and primary.data.get(f) in (None, ""):
                primary.data[f] = v
        if other.data.get("notes") and other.data["notes"] not in (primary.data.get("notes") or ""):
            primary.data["notes"] = "\n".join(filter(None, [primary.data.get("notes"), other.data["notes"]]))
        other.action, other.note = "merged", f"Merged into row {primary.row}"


# ---------- merge plan against the database ----------

def plan_merge(rows: list[Row], existing: list[Application]) -> None:
    by_id = {a.id: a for a in existing}
    by_key: dict[tuple, Application] = {}
    by_company: dict[str, list[Application]] = {}
    for a in existing:
        ck = _ckey(a.company)
        by_company.setdefault(ck, []).append(a)
        if a.job_id:
            by_key.setdefault(("job", ck, a.job_id.lower()), a)
        elif a.title:
            by_key.setdefault(("title", ck, _tkey(a.title)), a)
    used: set[int] = set()

    for r in rows:
        if r.action != "add":
            continue
        key = _row_key(r)
        match = by_id.get(r.record_id) if r.record_id else None
        if match is None and r.record_id is None:
            match = by_key.get(key)
            company_records = [a for a in by_company.get(key[1], []) if a.id not in used]
            bare = next((a for a in company_records if not a.title and not a.job_id), None)
            if key[0] == "bare" and match is None:
                if bare:
                    match = bare
                elif company_records:
                    r.action, r.note = "unchanged", "Company already tracked with an application"
                    continue
            elif match is None and bare:
                match = bare  # a wishlist entry has now been applied to
        if match is None or match.id in used:
            continue
        used.add(match.id)
        r.target_id = match.id
        authoritative = r.record_id is not None  # file exported by this app: blanks clear values too
        for f, v in r.data.items():
            if (authoritative or v not in (None, "")) and getattr(match, f) != v:
                r.changes[f] = v
        r.action = "update" if r.changes else "unchanged"
        # Final flags: the import's flags for fields it changes, the record's existing flags for the rest.
        kept = [f for f in match.flags if f.split(":")[0] not in r.changes]
        # An import flag still holds when its field ends up with the imported value (changed or already equal).
        incoming = [f for f in r.flags if authoritative or (fld := f.split(":")[0]) in r.changes
                    or getattr(match, fld, None) == r.data.get(fld)]
        r.flags = list(dict.fromkeys(kept + incoming))


# ---------- analyze / commit ----------

def analyze(grid: Grid, opts: ImportOptions, session: Session, sheets: list[str], today: date | None = None) -> tuple[dict, list[Row]]:
    today = today or date.today()
    settings = services.get_settings(session)
    statuses = {s["name"]: s["kind"] for s in settings["statuses"]}

    header_idx = opts.header_row - 1 if opts.header_row else detect_header(grid)
    if header_idx >= len(grid):
        raise services.ValidationError("Header row is beyond the end of the sheet")
    width = max((len(r) for r in grid), default=0)
    headers = [cell_text(c.value) for c in grid[header_idx]] + [""] * (width - len(grid[header_idx]))
    mapping = opts.mapping if opts.mapping is not None else suggest_mapping(headers)
    if "company" not in mapping.values():
        raise services.ValidationError("Map a column to Company Name to continue")
    dupes = [f for f in set(mapping.values()) if f and f != APPEND_TO_NOTES and list(mapping.values()).count(f) > 1]
    if dupes:
        raise services.ValidationError(f"Each field can only be mapped once: {', '.join(FIELDS[f][0] for f in dupes)}")

    existing = list(session.exec(select(Application)))
    vocab = {
        "source": settings["sources"] + clean_vocab("source", [a.source for a in existing if a.source], settings["sources"]),
        "location": clean_vocab("location", [a.location for a in existing if a.location], []),
        "company": [a.company for a in existing],
    }
    values = _collect_values(grid, header_idx, mapping)
    suggestions = suggest(values, vocab)
    for raw_status, count in values.get("status", Counter()).items():
        target, reason = match_status(raw_status, list(statuses))
        if target and reason:
            suggestions.append(Suggestion("status", raw_status, target, count, reason))
    authoritative = "id" in mapping.values()
    declined = set(opts.declined) if opts.declined is not None else ({s.key for s in suggestions} if authoritative else set())
    norm = {(s.field, s.source): s.target for s in suggestions if s.key not in declined}

    rows: list[Row] = []
    issues: list[Issue] = []
    blank = 0
    for offset, cells in enumerate(grid[header_idx + 1:]):
        if _is_blank(cells):
            blank += 1
            continue
        row_no = header_idx + 2 + offset
        r, iss = parse_row(cells, row_no, headers, mapping, norm, statuses, opts.date_fixes.get(str(row_no)), today)
        rows.append(r)
        issues += iss

    # A record ID may appear only once (e.g. a row copied in Excel): later copies become new records.
    seen_ids: set[int] = set()
    for r in rows:
        if r.record_id is not None and not r.skip:
            if r.record_id in seen_ids:
                issues.append(Issue(r.row, r.company, "id", "warning", f"ID {r.record_id} appears more than once – imported as a new record"))
                r.record_id = None
            else:
                seen_ids.add(r.record_id)

    if opts.keep_duplicates is not None:
        keep = set(opts.keep_duplicates)
    else:
        keep = {g.id for g in find_duplicates([_copy_row(r) for r in rows], set())} if authoritative else set()
    groups = find_duplicates(rows, keep)
    if opts.mode == "merge":
        plan_merge(rows, existing)

    final = [r for r in rows if r.action in ("add", "update", "unchanged")]
    imported = [r for r in rows if r.action in ("add", "update")]
    counts = {
        "rows": len(rows),
        "blank": blank,
        "applications": sum(1 for r in final if not r.is_wishlist),
        "wishlist": sum(1 for r in final if r.is_wishlist),
        "companies": len({_ckey(r.data["company"]) for r in final if not r.is_wishlist}),
        "add": sum(r.action == "add" for r in rows),
        "update": sum(r.action == "update" for r in rows),
        "unchanged": sum(r.action == "unchanged" for r in rows),
        "skipped": sum(r.action in ("skip", "merged") for r in rows),
        "flagged": sum(1 for r in imported if r.flags),
        "errors": sum(i.level == "error" for i in issues),
        "warnings": sum(i.level == "warning" for i in issues),
        "existing": len(existing),
    }
    samples: dict[int, list[str]] = {i: [] for i in range(width)}
    for cells in grid[header_idx + 1:]:
        if _is_blank(cells):
            continue
        for i, c in enumerate(cells):
            if len(samples[i]) < MAX_PREVIEW_SAMPLES and (t := cell_text(c.value)):
                samples[i].append(t[:60])

    result = {
        "sheets": sheets,
        "sheet": opts.sheet or sheets[0],
        "header_row": header_idx + 1,
        "mode": opts.mode,
        "headers": [{"index": i, "text": h, "field": mapping.get(str(i)), "samples": samples.get(i, [])} for i, h in enumerate(headers)],
        "mapping": mapping,
        "fields": [{"key": k, "label": v[0]} for k, v in FIELDS.items()],
        "suggestions": [{**s.__dict__, "key": s.key, "approved": s.key not in declined} for s in suggestions],
        "duplicates": [g.__dict__ for g in groups],
        "issues": [i.__dict__ for i in issues],
        "rows": [_row_preview(r) for r in rows],
        "counts": counts,
    }
    return result, rows


def _copy_row(r: Row) -> Row:
    return Row(row=r.row, company=r.company, data=dict(r.data), skip=r.skip, action=r.action, last_updated=r.last_updated)


def parse_history_sheet(grid: Grid) -> dict[int, list[tuple[str | None, str, datetime]]]:
    """Read the 'Status History' sheet of our own export: application ID -> [(from, to, changed_at)]."""
    if not grid:
        return {}
    head = {_hkey(cell_text(c.value)): i for i, c in enumerate(grid[0])}
    need = ["applicationid", "fromstatus", "tostatus", "changedat"]
    if not all(k in head for k in need):
        return {}
    out: dict[int, list[tuple[str | None, str, datetime]]] = {}
    for cells in grid[1:]:
        get = lambda k: cells[head[k]].value if head[k] < len(cells) else None  # noqa: E731
        try:
            app_id, to, at = int(float(get("applicationid"))), clean_text(get("tostatus")), parse_datetime(get("changedat"))
        except (TypeError, ValueError):
            continue
        if to and at:
            out.setdefault(app_id, []).append((clean_text(get("fromstatus")), to, at))
    return out


def _row_preview(r: Row) -> dict:
    d = r.data
    return {
        "row": r.row, "action": r.action, "note": r.note or r.skip, "company": r.company,
        "title": d.get("title"), "job_id": d.get("job_id"),
        "date_applied": d["date_applied"].isoformat() if d.get("date_applied") else None,
        "status": d.get("status"), "source": d.get("source"), "location": d.get("location"),
        "flags": r.flags, "changes": sorted(r.changes),
    }


def commit(rows: list[Row], mode: str, session: Session, history: dict | None = None) -> dict:
    """Write the analysed rows. `history` (from our export's Status History sheet) replaces the generated
    history of records that carry an ID, so a round trip keeps every status change."""
    if mode == "replace":
        session.exec(delete(StatusHistory))
        session.exec(delete(Application))
        session.flush()
    added = updated = 0
    id_map: dict[int, int] = {}  # record ID in the file -> ID in the database
    for r in rows:
        if r.action == "add":
            app = services.create_application(
                session, ApplicationCreate.model_validate(r.data), flags=r.flags, last_updated=r.last_updated,
                created_at=r.created_at, record_id=r.record_id if mode == "replace" else None, commit=False,
            )
            if r.record_id is not None:
                id_map[r.record_id] = app.id
            added += 1
        elif r.action == "update":
            app = session.get(Application, r.target_id)
            old_status = app.status
            for f, v in r.changes.items():
                setattr(app, f, v)
            app.flags = r.flags  # final flags computed by plan_merge
            app.last_updated = r.last_updated if r.record_id is not None and r.last_updated else now()
            session.add(app)
            if app.status != old_status:
                services.log_status(session, app, old_status)
            if r.record_id is not None:
                id_map[r.record_id] = app.id
            updated += 1
    session.flush()
    for file_id, db_id in id_map.items():
        entries = (history or {}).get(file_id)
        if not entries:
            continue
        session.exec(delete(StatusHistory).where(StatusHistory.application_id == db_id))
        ordered = sorted(entries, key=lambda e: e[2])  # stable: same-time entries keep the sheet's order
        for frm, to, at in ordered:
            session.add(StatusHistory(application_id=db_id, from_status=frm, to_status=to, changed_at=at))
        app = session.get(Application, db_id)
        last = ordered[-1][1]
        if app.status != last:  # status edited in Excel after export
            services.log_status(session, app, last)
    session.commit()
    written = [r for r in rows if r.action in ("add", "update")]
    return {
        "added": added,
        "updated": updated,
        "unchanged": sum(r.action == "unchanged" for r in rows),
        "skipped": sum(r.action in ("skip", "merged") for r in rows),
        "flagged": sum(1 for r in written if r.flags),
    }
