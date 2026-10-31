from datetime import date, datetime
from typing import Optional

from pydantic import NaiveDatetime, field_validator
from sqlalchemy import JSON, Column, ForeignKey, Integer, Text
from sqlmodel import Field, SQLModel

from .constants import WORK_MODES


def now() -> datetime:
    return datetime.now().replace(microsecond=0)


class ApplicationBase(SQLModel):
    company: str = Field(min_length=1, max_length=200, index=True)
    title: Optional[str] = None
    job_id: Optional[str] = None
    date_applied: Optional[date] = None
    source: Optional[str] = None
    job_link: Optional[str] = Field(default=None, sa_column=Column(Text))
    location: Optional[str] = None
    work_mode: Optional[str] = None
    status: str = Field(default="Applied", index=True)
    next_follow_up: Optional[date] = None
    contact_person: Optional[str] = None
    contact_info: Optional[str] = None
    salary_range: Optional[str] = None
    notes: Optional[str] = Field(default=None, sa_column=Column(Text))

    @field_validator(
        "company", "title", "job_id", "source", "job_link", "location", "work_mode", "status",
        "contact_person", "contact_info", "salary_range", "notes",
        mode="before",
    )
    @classmethod
    def _strip(cls, v):
        if isinstance(v, str):
            v = " ".join(v.split()) if "\n" not in v.strip() else v.strip()
            return v or None
        return v

    @field_validator("job_link")
    @classmethod
    def _link(cls, v):
        if v and not v.lower().startswith(("http://", "https://")):
            raise ValueError("Job link must start with http:// or https://")
        return v

    @field_validator("work_mode")
    @classmethod
    def _mode(cls, v):
        if v and v not in WORK_MODES:
            raise ValueError(f"Work mode must be one of {', '.join(WORK_MODES)}")
        return v


class Application(ApplicationBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: NaiveDatetime = Field(default_factory=now)
    last_updated: NaiveDatetime = Field(default_factory=now)
    # Review flags raised on import (e.g. "date_applied_future"); cleared when the user edits the field.
    flags: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False, default=list))


class ApplicationCreate(ApplicationBase):
    pass


class ApplicationUpdate(ApplicationBase):
    """All fields optional; only fields present in the request are applied."""

    company: Optional[str] = None
    status: Optional[str] = None
    flags: Optional[list[str]] = None


class ApplicationRead(ApplicationBase):
    id: int
    created_at: NaiveDatetime
    last_updated: NaiveDatetime
    flags: list[str]
    status_since: NaiveDatetime | None = None  # when the current status was entered (from history)


class StatusHistory(SQLModel, table=True):
    __tablename__ = "status_history"

    id: Optional[int] = Field(default=None, primary_key=True)
    application_id: int = Field(
        sa_column=Column(Integer, ForeignKey("application.id", ondelete="CASCADE"), index=True, nullable=False)
    )
    from_status: Optional[str] = None
    to_status: str
    changed_at: NaiveDatetime = Field(default_factory=now)


class Setting(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: dict | list | int | str = Field(sa_column=Column(JSON, nullable=False))


class BulkStatus(SQLModel):
    ids: list[int]
    status: str


class BulkIds(SQLModel):
    ids: list[int]


class StatusListUpdate(SQLModel):
    statuses: list[dict]
    renames: dict[str, str] = {}  # old name -> new name, applied to records and history
