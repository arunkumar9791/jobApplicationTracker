"""Read .xlsx / .xls / .csv into a plain grid of cells, keeping hyperlink targets."""

import csv
import io
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePath
from typing import Any


@dataclass
class Cell:
    value: Any = None
    link: str | None = None  # hyperlink target, which can differ from the (often truncated) cell text


Grid = list[list[Cell]]


class SpreadsheetError(ValueError):
    pass


def sheet_names(content: bytes, filename: str) -> list[str]:
    kind = _kind(filename)
    if kind == "csv":
        return ["CSV"]
    if kind == "xlsx":
        return _open_xlsx(content).sheetnames
    return _open_xls(content).sheet_names()


def read_sheet(content: bytes, filename: str, sheet: str | None = None) -> Grid:
    kind = _kind(filename)
    if kind == "csv":
        return _read_csv(content)
    if kind == "xlsx":
        return _read_xlsx(content, sheet)
    return _read_xls(content, sheet)


def _kind(filename: str) -> str:
    ext = PurePath(filename).suffix.lower()
    if ext in (".xlsx", ".xlsm"):
        return "xlsx"
    if ext == ".xls":
        return "xls"
    if ext in (".csv", ".tsv", ".txt"):
        return "csv"
    raise SpreadsheetError(f"Unsupported file type '{ext}'. Use .xlsx, .xls or .csv")


def _open_xlsx(content: bytes):
    from openpyxl import load_workbook

    try:
        # Not read_only: hyperlinks are only available in normal mode.
        return load_workbook(io.BytesIO(content), data_only=True)
    except Exception as e:  # openpyxl raises many types for corrupt files
        raise SpreadsheetError(f"Could not read Excel file: {e}") from e


def _read_xlsx(content: bytes, sheet: str | None) -> Grid:
    wb = _open_xlsx(content)
    ws = wb[sheet] if sheet else wb.worksheets[0]
    return [[Cell(c.value, c.hyperlink.target if c.hyperlink else None) for c in row] for row in ws.iter_rows()]


def _open_xls(content: bytes):
    import xlrd

    try:
        return xlrd.open_workbook(file_contents=content)
    except Exception as e:
        raise SpreadsheetError(f"Could not read .xls file: {e}") from e


def _read_xls(content: bytes, sheet: str | None) -> Grid:
    import xlrd

    wb = _open_xls(content)
    ws = wb.sheet_by_name(sheet) if sheet else wb.sheet_by_index(0)
    links = getattr(ws, "hyperlink_map", {}) or {}
    grid: Grid = []
    for r in range(ws.nrows):
        row = []
        for c in range(ws.ncols):
            cell = ws.cell(r, c)
            value: Any = cell.value
            if cell.ctype == xlrd.XL_CELL_DATE:
                value = xlrd.xldate_as_datetime(cell.value, wb.datemode)
            elif cell.ctype == xlrd.XL_CELL_EMPTY:
                value = None
            link = links.get((r, c))
            row.append(Cell(value, link.url_or_path if link else None))
        grid.append(row)
    return grid


def _read_csv(content: bytes) -> Grid:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise SpreadsheetError("Could not decode CSV file (expected UTF-8)")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    return [[Cell(v if v != "" else None) for v in row] for row in csv.reader(io.StringIO(text), dialect)]


def cell_text(value: Any) -> str:
    """Display text for previews."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%d-%m-%Y") if value.time() == datetime.min.time() else value.isoformat(sep=" ")
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return " ".join(str(value).split())
