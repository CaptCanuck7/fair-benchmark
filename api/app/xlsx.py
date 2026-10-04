"""Safe reading of uploaded and bundled Excel workbooks.

Workbooks are opened read-only with data_only=True, so formulas are never
evaluated (cached values are read instead) and macros are never run. openpyxl
parses the XML with defusedxml when it is installed, which it is (see
pyproject.toml).
"""

import io
import zipfile
from collections.abc import Iterator
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.workbook.workbook import Workbook

MAX_ROWS = 10_000
MAX_COLS = 60


class WorkbookError(ValueError):
    """The file is not a workbook we can read. The message is shown to the analyst."""


def open_workbook(source: bytes | Path) -> Workbook:
    data = source.read_bytes() if isinstance(source, Path) else source
    if not zipfile.is_zipfile(io.BytesIO(data)):
        raise WorkbookError("That file isn’t an .xlsx workbook.")
    try:
        return load_workbook(io.BytesIO(data), read_only=True, data_only=True, keep_links=False)
    except Exception as exc:  # openpyxl raises many types for damaged files
        raise WorkbookError("That file couldn’t be read as an .xlsx workbook.") from exc


def cell(value: Any) -> Any:
    """Normalize a cell value: trimmed strings (empty -> None), dates as ISO strings."""
    if isinstance(value, str):
        value = value.strip()
        return value or None
    if isinstance(value, datetime):
        return value.date().isoformat() if value.time() == time(0) else value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def sheet_rows(ws) -> Iterator[tuple[int, list[Any]]]:
    """Yield (spreadsheet row number, normalized cells) for each row, header included."""
    for n, row in enumerate(ws.iter_rows(max_col=MAX_COLS, values_only=True), start=1):
        if n > MAX_ROWS + 1:
            raise WorkbookError(f"The sheet has more than {MAX_ROWS:,} rows.")
        yield n, [cell(v) for v in row]
