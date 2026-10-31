"""Value parsing for spreadsheet cells. Day-first everywhere: 03-04-2026 is 3 April, never 4 March."""

import re
from datetime import date, datetime, timedelta

EXCEL_EPOCH = date(1899, 12, 30)
# Serials for 1960..2100; anything outside is treated as a plain number, not a date.
SERIAL_RANGE = (21916, 73051)

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}

_DMY = re.compile(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{2}|\d{4})$")
_YMD = re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$")
_D_MON_Y = re.compile(r"^(\d{1,2})[\s-]([A-Za-z]{3,9})[\s,-]+(\d{4})$")
_MON_D_Y = re.compile(r"^([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(\d{4})$")


def _year(y: str) -> int:
    n = int(y)
    return n + 2000 if len(y) == 2 else n


def _month(name: str) -> int | None:
    return _MONTHS.get(name[:3].lower())


def parse_date(value) -> date | None:
    """Parse a cell value into a date. Returns None for blanks; raises ValueError if unparseable."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, bool):
        raise ValueError(f"Not a date: {value!r}")
    if isinstance(value, (int, float)):
        return _from_serial(value)

    s = str(value).strip()
    if not s:
        return None
    if re.fullmatch(r"\d+(\.\d+)?", s):
        return _from_serial(float(s))

    try:
        if m := _DMY.match(s):
            d, mo, y = m.groups()
            return date(_year(y), int(mo), int(d))
        if m := _YMD.match(s):
            y, mo, d = m.groups()
            return date(int(y), int(mo), int(d))
        if m := _D_MON_Y.match(s):
            d, mon, y = m.groups()
            if mo := _month(mon):
                return date(int(y), mo, int(d))
        if m := _MON_D_Y.match(s):
            mon, d, y = m.groups()
            if mo := _month(mon):
                return date(int(y), mo, int(d))
        # ISO timestamps, e.g. 2026-10-23T12:46:49.575Z
        if re.match(r"^\d{4}-\d{2}-\d{2}[T ]", s):
            return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError as e:
        raise ValueError(f"Invalid date: {s!r}") from e
    raise ValueError(f"Unrecognised date format: {s!r}")


def _from_serial(n: float) -> date:
    if not SERIAL_RANGE[0] <= n <= SERIAL_RANGE[1]:
        raise ValueError(f"Number {n} is not a plausible Excel date")
    return EXCEL_EPOCH + timedelta(days=int(n))


def parse_datetime(value) -> datetime | None:
    """Like parse_date but keeps the time part when present (used for Last Updated)."""
    if isinstance(value, datetime):
        # Excel stores times as fractions of a day, so 12:00:00 can read back as 11:59:59.999; round to the second.
        value = value.replace(tzinfo=None)
        if value.microsecond >= 500_000:
            value += timedelta(seconds=1)
        return value.replace(microsecond=0)
    if isinstance(value, str) and re.match(r"^\d{4}-\d{2}-\d{2}[T ]\d", value.strip()):
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        return dt.replace(tzinfo=None, microsecond=0)
    d = parse_date(value)
    return datetime(d.year, d.month, d.day) if d else None


def date_flag(d: date | None, today: date | None = None) -> str | None:
    """Flag dates that are probably mistakes: in the future, or more than a year old."""
    if d is None:
        return None
    today = today or date.today()
    if d > today:
        return "future"
    if d < today - timedelta(days=365):
        return "old"
    return None


def clean_text(value) -> str | None:
    """Trim and collapse whitespace; numbers that are whole become integers ('854617.0' -> '854617')."""
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    s = " ".join(str(value).split())
    return s or None
