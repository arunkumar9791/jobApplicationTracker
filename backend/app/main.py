import secrets
from collections import OrderedDict
from contextlib import asynccontextmanager
from datetime import date
from typing import Any

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from sqlmodel import Session, select

from . import exporter, importer, kpis, services, spreadsheet
from .db import get_session, init_db
from .models import (
    Application,
    ApplicationCreate,
    ApplicationRead,
    ApplicationUpdate,
    BulkIds,
    BulkStatus,
    StatusListUpdate,
    StatusHistory,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="Job Application Tracker", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(services.ValidationError)
@app.exception_handler(spreadsheet.SpreadsheetError)
async def _validation_error(_, exc: ValueError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


def _get(session: Session, app_id: int) -> Application:
    app_ = session.get(Application, app_id)
    if not app_:
        raise HTTPException(404, "Application not found")
    return app_


# ---------- applications ----------

def _read(session: Session, apps: list[Application]) -> list[ApplicationRead]:
    since = services.status_since(session, None if len(apps) > 50 else [a.id for a in apps])
    return [ApplicationRead(**a.model_dump(), status_since=since.get(a.id)) for a in apps]


@app.get("/api/applications", response_model=list[ApplicationRead])
def list_applications(session: Session = Depends(get_session)):
    return _read(session, list(session.exec(select(Application).order_by(Application.id))))


@app.post("/api/applications", response_model=ApplicationRead, status_code=201)
def create_application(data: ApplicationCreate, session: Session = Depends(get_session)):
    return _read(session, [services.create_application(session, data)])[0]


@app.get("/api/applications/{app_id}", response_model=ApplicationRead)
def read_application(app_id: int, session: Session = Depends(get_session)):
    return _read(session, [_get(session, app_id)])[0]


@app.patch("/api/applications/{app_id}", response_model=ApplicationRead)
def update_application(app_id: int, data: ApplicationUpdate, session: Session = Depends(get_session)):
    return _read(session, [services.update_application(session, _get(session, app_id), data)])[0]


@app.delete("/api/applications/{app_id}", status_code=204)
def delete_application(app_id: int, session: Session = Depends(get_session)):
    _get(session, app_id)
    services.delete_applications(session, [app_id])


@app.get("/api/applications/{app_id}/history", response_model=list[StatusHistory])
def application_history(app_id: int, session: Session = Depends(get_session)):
    _get(session, app_id)
    return services.history(session, app_id)


@app.post("/api/applications/bulk/status")
def bulk_status(body: BulkStatus, session: Session = Depends(get_session)):
    return {"changed": services.set_status(session, body.ids, body.status)}


@app.post("/api/applications/bulk/delete")
def bulk_delete(body: BulkIds, session: Session = Depends(get_session)):
    return {"deleted": services.delete_applications(session, body.ids)}


# ---------- dashboard ----------

@app.get("/api/dashboard")
def dashboard(
    start: date | None = None,
    end: date | None = None,
    source: str | None = None,
    location: str | None = None,
    session: Session = Depends(get_session),
):
    apps = list(session.exec(select(Application)))
    history = list(session.exec(select(StatusHistory)))
    statuses = services.get_settings(session)["statuses"]
    return kpis.compute(apps, history, statuses, date.today(), kpis.Filters(start, end, source, location))


# ---------- settings ----------

@app.get("/api/settings")
def get_settings(session: Session = Depends(get_session)):
    return services.get_settings(session)


@app.put("/api/settings")
def put_settings(values: dict[str, Any], session: Session = Depends(get_session)):
    if "statuses" in values:
        raise HTTPException(422, "Use PUT /api/settings/statuses to change the status list")
    return services.update_settings(session, values)


@app.put("/api/settings/statuses")
def put_statuses(body: StatusListUpdate, session: Session = Depends(get_session)):
    return services.update_statuses(session, body.statuses, body.renames)


# ---------- backup ----------

@app.get("/api/backup")
def backup(session: Session = Depends(get_session)):
    data = services.backup(session)
    filename = f"job-tracker-backup-{data['exported_at'][:10]}.json"
    return JSONResponse(data, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.post("/api/restore")
def restore(data: dict[str, Any], session: Session = Depends(get_session)):
    return services.restore(session, data)


# ---------- import ----------

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
# Uploaded files are kept in memory between wizard steps (single user; a restart just means re-uploading).
_uploads: "OrderedDict[str, tuple[str, bytes]]" = OrderedDict()


def _upload(token: str) -> tuple[str, bytes]:
    if token not in _uploads:
        raise HTTPException(404, "Upload expired – please choose the file again")
    return _uploads[token]


@app.post("/api/import/upload")
async def import_upload(file: UploadFile = File(...)):
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File is larger than 20 MB")
    name = file.filename or "upload"
    sheets = spreadsheet.sheet_names(content, name)
    token = secrets.token_urlsafe(12)
    _uploads[token] = (name, content)
    while len(_uploads) > 5:
        _uploads.popitem(last=False)
    sizes = []
    for sheet in sheets:
        grid = spreadsheet.read_sheet(content, name, None if sheet == "CSV" else sheet)
        sizes.append({"name": sheet, "rows": sum(1 for r in grid if any(c.value not in (None, "") for c in r))})
    return {"token": token, "filename": name, "sheets": sizes}


HISTORY_SHEET = "Status History"


def _run_analysis(opts: importer.ImportOptions, session: Session):
    name, content = _upload(opts.token)
    sheets = spreadsheet.sheet_names(content, name)
    if opts.sheet and opts.sheet not in sheets:
        raise HTTPException(422, f"Sheet '{opts.sheet}' not found")
    sheet = opts.sheet or ("Applications" if "Applications" in sheets else sheets[0])
    grid = spreadsheet.read_sheet(content, name, None if sheet == "CSV" else sheet)
    result, rows = importer.analyze(grid, opts.model_copy(update={"sheet": sheet}), session, sheets)
    history = None
    if HISTORY_SHEET in sheets and sheet != HISTORY_SHEET:
        history = importer.parse_history_sheet(spreadsheet.read_sheet(content, name, HISTORY_SHEET))
    return result, rows, history


@app.post("/api/import/analyze")
def import_analyze(opts: importer.ImportOptions, session: Session = Depends(get_session)):
    result, _, _ = _run_analysis(opts, session)
    return result


@app.post("/api/import/commit")
def import_commit(opts: importer.ImportOptions, session: Session = Depends(get_session)):
    _, rows, history = _run_analysis(opts, session)
    summary = importer.commit(rows, opts.mode, session, history)
    _uploads.pop(opts.token, None)
    return summary


# ---------- export ----------

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _download(content: bytes, filename: str, media_type: str) -> Response:
    return Response(content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/api/export/xlsx")
def export_xlsx(session: Session = Depends(get_session)):
    apps = list(session.exec(select(Application)))
    history = list(session.exec(select(StatusHistory)))
    content, _ = exporter.build_workbook(apps, history, services.get_settings(session))
    return _download(content, f"job-applications-{date.today():%Y-%m-%d}.xlsx", XLSX)


class ViewExport(BaseModel):
    ids: list[int]
    fields: list[str] = []
    format: str = "xlsx"


@app.post("/api/export/view")
def export_view(body: ViewExport, session: Session = Depends(get_session)):
    if body.format not in ("csv", "xlsx"):
        raise HTTPException(422, "format must be csv or xlsx")
    by_id = {a.id: a for a in session.exec(select(Application).where(Application.id.in_(body.ids)))}
    apps = [by_id[i] for i in body.ids if i in by_id]  # keep the on-screen order
    content = exporter.build_view(apps, body.fields, body.format)
    name = f"job-applications-view-{date.today():%Y-%m-%d}.{body.format}"
    return _download(content, name, "text/csv; charset=utf-8" if body.format == "csv" else XLSX)
