# Job Application Tracker

A local, single-user web app for tracking job applications. Imports your existing spreadsheet and (from Phase 4) exports an `.xlsx` with a live, formula-driven dashboard.

- **Frontend:** React 19 + TypeScript + Vite, Tailwind CSS v4, TanStack Table v9 (virtualised), TanStack Query
- **Backend:** FastAPI + SQLite (SQLModel). XlsxWriter will produce native Excel charts in Phase 4.

## Setup

Requires **Python 3.13** and **Node 20+**.

```bash
brew install python@3.13   # if needed
npm install                # root tooling (concurrently)
npm run setup              # creates backend/.venv and installs frontend deps
```

## Run

```bash
npm run dev
```

- App: http://localhost:5173
- API: http://localhost:8000 (interactive docs at `/docs`)

On first start the database (`backend/data/tracker.db`) is seeded from `fixtures/jobs_sheet.xlsx` through the importer, with its default suggestions accepted. It is never re-seeded once it has data. To reset it to the fixture:

```bash
npm run seed -- --force
```

## Test

```bash
npm test          # backend (pytest) + frontend (vitest)
```

## Data model

| Field | Notes |
|---|---|
| `company` | required |
| `title`, `job_id`, `source`, `location`, `contact_person`, `contact_info`, `salary_range`, `notes` | text; Job ID stays text, so leading zeros are kept |
| `date_applied`, `next_follow_up` | dates |
| `job_link` | unlimited length; must be `http(s)://` |
| `work_mode` | Onsite / Hybrid / Remote |
| `status` | one of the configured statuses (Interview Stage is folded into this) |
| `last_updated` | set automatically on every change |
| `created_at`, `id` | internal |
| `flags` | review flags such as `date_applied:future`; editing the field clears its flag |

Every status change is written to `status_history` (from, to, timestamp). That history drives time-in-stage and response-time KPIs.

Statuses carry a **kind** (`wishlist`, `applied`, `interview`, `offer`, `rejected`, `closed`). KPIs count by kind, so renamed or added statuses still count correctly.

## Import (Excel / CSV)

**Import** tab: upload `.xlsx`, `.xls` or `.csv` and pick the sheet. The header row and column mapping are detected automatically, and you can change either. Unknown columns default to *Append to notes*, so nothing is lost. Before anything is written you review:

- **Normalise values**: suggested merges for typos and variants (`Copmay Site` → Company Site, `Banglore`/`Bangalore` → Bengaluru, `Interviewing` → Screening). Each one can be declined.
- **Duplicates**: same Company + Job ID, or Company + Title when there's no Job ID, plus wishlist rows for companies you've already applied to. Choose *Merge* or *Keep both*.
- **Issues**: unreadable dates, dates in the future or more than a year old (with a one-click year fix), missing applied dates, unknown statuses, rows without a company.
- **Preview**: what happens to every row (add / update / no change / duplicate / skip).

Dates are read day-first (`03-04-2026` is 3 April), and ISO timestamps and Excel serial numbers are also accepted. Job IDs stay text. For links, the real hyperlink target is used, not the cell's display text. Rows with only a company name become **Wishlist**. Flagged rows are imported and shown under **Needs review** in the Applications table.

**Merge** updates matching records (matched by record ID, then Company + Job ID / Title) and adds new ones. Blank cells don't wipe existing values, unless the file was exported by this app (it has an `ID` column), in which case the file wins. **Replace all** deletes everything first.

## Export to Excel

**Download Excel** (Dashboard), **Export → Full workbook** (Applications) or **Settings → Excel workbook** produce one `.xlsx` (built with XlsxWriter on the backend, because the browser-side libraries can't create native charts):

- **Dashboard**: 9 KPI tiles plus a table of all 16 KPIs, every one a live formula (`COUNTIFS`, `SUMIFS`, `AVERAGE`, `TODAY()`) over the Applications sheet, also available as named ranges (`KPI_response_rate`, …). 7 **native Excel charts** (weekly, funnel, source count and response rate, status, location, work mode) read formula-driven helper tables on the same sheet, so editing data in Excel updates tiles and charts.
- **Applications**: an Excel Table with a frozen header and filters, dates as real dates (`DD-MM-YYYY`), clickable links, **dropdowns** for Status (strict), Source (list or free text) and Work Mode, and conditional formatting (status colours, future applied dates in amber, overdue follow-ups in red). Grey columns are calculated per row (Status Kind, Interviewed, Responded, Days to Response, …); Excel fills them into rows you add inside the table. Hidden, collapsible columns carry facts from the app's status history plus the record ID, so re-importing is lossless.
- **Lists** (hidden): statuses with their kind, funnel order, sources, work modes.
- **Status History**: every status change.

Formulas use plain cell ranges (no structured references) so the file also works in Google Sheets. The tested range is your data plus 2,000 spare rows.

**Round trip:** importing an exported file changes nothing by default: suggestions are unticked, duplicates are kept, record IDs and the Status History sheet are restored. Status or field edits made in Excel are applied (a status change is added to the history).

**Current view:** Applications → Export → *Current view* (.xlsx or .csv) downloads exactly the filtered rows, in the on-screen order, with the visible columns.

## KPI definitions

The **Dashboard** computes these on the backend (`backend/app/kpis.py`), so the app and the Excel export (Phase 4) share one definition. Status *kinds* drive everything:

| KPI | Definition |
|---|---|
| Applications | records whose status isn't Wishlist (date-range filter applies to Date Applied) |
| This week / this month | applied Monday–today / 1st–today; ignore the date-range filter |
| Active | currently Applied, an interview stage, or Offer/Accepted |
| Interviews | reached Screening or later at any point (current status or history), including rejected-after-interview |
| Offers | reached Offer or Accepted at any point |
| Rejections | currently Rejected |
| **Response rate** | (reached an interview stage or offer, **or rejected**) ÷ applications. A rejection counts as a response because the company replied. Withdrawn and Ghosted alone do not |
| Interview / offer rate | interviews ÷ applications, offers ÷ applications |
| Avg days to response | Date Applied → first status change that counts as a response; future-dated applications are excluded |
| Follow-ups overdue / due this week | Next Follow-up before today / within the next 7 days, on records that aren't Rejected/Withdrawn/Ghosted |

Charts: applications per week, pipeline funnel (share that reached each stage), current status, applications and response rate by source (two charts, never a dual axis), location (multi-city roles count once per city) and work mode. Each chart has a **Table** view. Future-dated and undated applications count in totals but are left out of the weekly chart; a banner links to them.

## Backup

**Settings → Download backup** saves a JSON snapshot (records, history and settings). **Restore from file** replaces everything with a snapshot.

## Screens

- **Dashboard**: KPI tiles, charts, date-range / source / location filters, Excel download.
- **Pipeline**: Kanban board by status. Drag a card to change its status (mouse, touch, or keyboard: focus a card, Space, arrow keys, Space). Each move is logged; cards show time in stage. Wishlist and closed columns can be toggled.
- **Applications**: virtualised table (fast with 1,000+ rows) with search, per-column filters, sorting, inline edit (double-click), bulk status change and delete, column show/hide, export.
- **Follow-ups**: overdue and due-this-week reminders (Done → +7 days, reschedule, clear) and **stale** applications (Applied with no update for N days, default 14, editable on the page). The tab shows a badge with the number due.
- **Wishlist**: target companies with search, quick add (warns about duplicates) and one-click **Mark applied** (status Applied, dated today).
- **Import** and **Settings** (backup/restore, stale days, the status pipeline, and sources). Statuses can be renamed (records and history follow), reordered (board and funnel order), re-kinded, added or removed (refused while records still use them). *Wishlist* and *Applied* are core and locked.

## Definition of done

| Requirement | Status |
|---|---|
| Importing the real file gives correct counts | ✅ 16 applications / 9 companies; 129 company-only rows → 128 wishlist + 1 Atlassian duplicate (test `test_fixture_counts_flags_and_suggestions`) |
| Flags the 2027–2029 dates | ✅ flagged, with a one-click "Use 23-10-2026" fix |
| Suggests merges for location and source typos | ✅ `Copmay Site`, `Banglore`, `Bangalore` |
| App KPIs = exported Excel formulas | ✅ all 16 KPIs, recalculated with the `formulas` engine (`test_kpi_parity_with_excel_formulas`) |
| Export → import round trip without loss | ✅ every field, ID, timestamp, flag and history entry (`test_round_trip_replace_is_lossless`) |
| Opens in Excel and Google Sheets with charts, dropdowns, filters | ⚠️ structure is tested (native chart parts, validations, table, filters), but not yet opened in Excel or Google Sheets |
| Unit tests: date parsing, normalisation, duplicates, KPIs | ✅ `test_parsing.py`, `test_importer.py`, `test_kpis.py` |

## Build phases

1. ✅ Data model, storage, CRUD, Applications table
2. ✅ Excel/CSV import with mapping, validation and normalisation
3. ✅ Dashboard (KPIs + charts) and filters
4. ✅ Excel export with formula-driven dashboard and native charts, plus round-trip test
5. ✅ Kanban, follow-ups, wishlist, polish
