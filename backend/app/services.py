"""Business logic shared by the API, seed script and (later) the importer."""

import copy
from datetime import datetime, time
from typing import Any

from sqlalchemy import func, update
from sqlmodel import Session, delete, select

from .constants import DEFAULT_SETTINGS, STATUS_KINDS

# The importer and new records rely on these two names, so they can't be renamed, removed or re-kinded.
CORE_STATUSES = {"Wishlist": "wishlist", "Applied": "applied"}
from .models import Application, ApplicationCreate, ApplicationUpdate, Setting, StatusHistory, now


class ValidationError(ValueError):
    pass


# ---------- settings ----------

def get_settings(session: Session) -> dict[str, Any]:
    stored = {s.key: s.value for s in session.exec(select(Setting))}
    return {k: stored.get(k, copy.deepcopy(v)) for k, v in DEFAULT_SETTINGS.items()}


def _validate_settings(values: dict[str, Any]) -> None:
    unknown = set(values) - set(DEFAULT_SETTINGS)
    if unknown:
        raise ValidationError(f"Unknown settings: {', '.join(sorted(unknown))}")
    if "statuses" in values:
        statuses = values["statuses"]
        names = [s.get("name", "").strip() for s in statuses]
        if not all(names) or len(set(names)) != len(names):
            raise ValidationError("Status names must be non-empty and unique")
        if any(s.get("kind") not in STATUS_KINDS for s in statuses):
            raise ValidationError(f"Status kind must be one of {', '.join(STATUS_KINDS)}")
    if "stale_days" in values and (not isinstance(values["stale_days"], int) or values["stale_days"] < 1):
        raise ValidationError("stale_days must be a positive integer")


def update_settings(session: Session, values: dict[str, Any]) -> dict[str, Any]:
    _validate_settings(values)
    for key, value in values.items():
        session.merge(Setting(key=key, value=value))
    session.commit()
    return get_settings(session)


def update_statuses(session: Session, statuses: list[dict], renames: dict[str, str]) -> dict[str, Any]:
    """Replace the status list. Renames are applied to every record and history entry; a status that
    is removed while records still use it is refused."""
    _validate_settings({"statuses": statuses})
    by_name = {s["name"]: s for s in statuses}
    for name, kind in CORE_STATUSES.items():
        if by_name.get(name, {}).get("kind") != kind:
            raise ValidationError(f"'{name}' is a core status: keep it, with kind '{kind}'")
    renames = {old: new for old, new in renames.items() if old != new}
    if set(renames) & set(CORE_STATUSES):
        raise ValidationError("Core statuses can't be renamed")
    if missing := [new for new in renames.values() if new not in by_name]:
        raise ValidationError(f"Renamed status not in the list: {', '.join(missing)}")
    for old, new in renames.items():
        session.exec(update(Application).where(Application.status == old).values(status=new))
        session.exec(update(StatusHistory).where(StatusHistory.to_status == old).values(to_status=new))
        session.exec(update(StatusHistory).where(StatusHistory.from_status == old).values(from_status=new))
    in_use = session.exec(
        select(Application.status, func.count()).where(Application.status.not_in(list(by_name))).group_by(Application.status)
    ).all()
    if in_use:
        session.rollback()
        detail = ", ".join(f"'{name}' ({n} record{'s' if n > 1 else ''})" for name, n in in_use)
        raise ValidationError(f"Still in use: {detail}. Move those records to another status first.")
    session.merge(Setting(key="statuses", value=statuses))
    session.commit()
    return get_settings(session)


def status_since(session: Session, ids: list[int] | None = None) -> dict[int, datetime]:
    """Application id -> time of its latest status change."""
    stmt = select(StatusHistory.application_id, func.max(StatusHistory.changed_at)).group_by(StatusHistory.application_id)
    if ids is not None:
        stmt = stmt.where(StatusHistory.application_id.in_(ids))
    return {app_id: at for app_id, at in session.exec(stmt)}


def status_names(session: Session) -> list[str]:
    return [s["name"] for s in get_settings(session)["statuses"]]


def _check_status(session: Session, status: str) -> None:
    if status not in status_names(session):
        raise ValidationError(f"Unknown status '{status}'")


# ---------- applications ----------

def log_status(session: Session, app: Application, from_status: str | None, at: datetime | None = None) -> None:
    session.add(StatusHistory(application_id=app.id, from_status=from_status, to_status=app.status, changed_at=at or now()))


def create_application(
    session: Session,
    data: ApplicationCreate,
    *,
    flags: list[str] | None = None,
    last_updated: datetime | None = None,
    created_at: datetime | None = None,
    record_id: int | None = None,
    commit: bool = True,
) -> Application:
    _check_status(session, data.status)
    app = Application.model_validate(data)
    app.flags = flags or []
    if record_id is not None:
        app.id = record_id
    if created_at:
        app.created_at = created_at
    if last_updated:
        app.last_updated = last_updated
    session.add(app)
    session.flush()
    _seed_history(session, app)
    if commit:
        session.commit()
        session.refresh(app)
    return app


def _seed_history(session: Session, app: Application) -> None:
    """Initial history. A record created past 'Applied' gets an Applied entry on its applied date,
    then the current status at last_updated, so response-time KPIs work for imported data."""
    kinds = {s["name"]: s["kind"] for s in get_settings(session)["statuses"]}
    applied_at = datetime.combine(app.date_applied, time()) if app.date_applied else app.created_at
    kind = kinds.get(app.status)
    if kind in ("wishlist", "applied"):
        log_status(session, app, None, applied_at if kind == "applied" else app.created_at)
    else:
        session.add(StatusHistory(application_id=app.id, from_status=None, to_status="Applied", changed_at=applied_at))
        log_status(session, app, "Applied", max(app.last_updated, applied_at))


def update_application(session: Session, app: Application, data: ApplicationUpdate) -> Application:
    changes = data.model_dump(exclude_unset=True)
    if "company" in changes and not changes["company"]:
        raise ValidationError("Company name is required")
    if "status" in changes:
        if not changes["status"]:
            raise ValidationError("Status is required")
        _check_status(session, changes["status"])

    explicit_flags = changes.pop("flags", None)
    old_status = app.status
    for field, value in changes.items():
        setattr(app, field, value)
    # Editing a field resolves its review flags (flags are "<field>:<reason>").
    flags = explicit_flags if explicit_flags is not None else [f for f in app.flags if f.split(":")[0] not in changes]
    app.flags = list(flags)

    if changes or explicit_flags is not None:
        app.last_updated = now()
    if app.status != old_status:
        log_status(session, app, old_status)
    session.add(app)
    session.commit()
    session.refresh(app)
    return app


def set_status(session: Session, ids: list[int], status: str) -> int:
    _check_status(session, status)
    apps = session.exec(select(Application).where(Application.id.in_(ids))).all()
    changed = 0
    for app in apps:
        if app.status != status:
            old = app.status
            app.status = status
            app.last_updated = now()
            log_status(session, app, old)
            changed += 1
    session.commit()
    return changed


def delete_applications(session: Session, ids: list[int]) -> int:
    apps = session.exec(select(Application).where(Application.id.in_(ids))).all()
    found = [a.id for a in apps]
    session.exec(delete(StatusHistory).where(StatusHistory.application_id.in_(found)))
    for app in apps:
        session.delete(app)
    session.commit()
    return len(apps)


def history(session: Session, app_id: int) -> list[StatusHistory]:
    stmt = select(StatusHistory).where(StatusHistory.application_id == app_id).order_by(StatusHistory.changed_at, StatusHistory.id)
    return list(session.exec(stmt))


# ---------- backup / restore ----------

BACKUP_VERSION = 1


def backup(session: Session) -> dict[str, Any]:
    return {
        "version": BACKUP_VERSION,
        "exported_at": now().isoformat(),
        "settings": get_settings(session),
        "applications": [a.model_dump(mode="json") for a in session.exec(select(Application).order_by(Application.id))],
        "status_history": [h.model_dump(mode="json") for h in session.exec(select(StatusHistory).order_by(StatusHistory.id))],
    }


def restore(session: Session, data: dict[str, Any]) -> dict[str, int]:
    if data.get("version") != BACKUP_VERSION:
        raise ValidationError("Unsupported or missing backup version")
    try:
        apps = [Application.model_validate(a) for a in data["applications"]]
        hist = [StatusHistory.model_validate(h) for h in data["status_history"]]
        # model_validate on table models skips type coercion, so convert dates/datetimes explicitly.
        for a, raw in zip(apps, data["applications"]):
            parsed = ApplicationCreate.model_validate(raw)
            for f in ("date_applied", "next_follow_up"):
                setattr(a, f, getattr(parsed, f))
            a.created_at = datetime.fromisoformat(raw["created_at"])
            a.last_updated = datetime.fromisoformat(raw["last_updated"])
        for h, raw in zip(hist, data["status_history"]):
            h.changed_at = datetime.fromisoformat(raw["changed_at"])
        settings = data.get("settings", {})
        _validate_settings(settings)
    except (KeyError, TypeError, ValueError) as e:
        raise ValidationError(f"Invalid backup file: {e}") from e

    session.exec(delete(StatusHistory))
    session.exec(delete(Application))
    session.exec(delete(Setting))
    session.add_all(Setting(key=k, value=v) for k, v in settings.items())
    session.add_all(apps)
    session.flush()
    session.add_all(hist)
    session.commit()
    return {"applications": len(apps), "status_history": len(hist)}
