"""Write a list of row dicts to a single-sheet Excel workbook.

Source-agnostic: the caller supplies the ordered headers (and optional per-column
widths); every source flattens its own records into ``dict[str, str]`` rows.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

# Excel's hard limit is 32,767 characters per cell.
_MAX_CELL = 32_000
_DEFAULT_WIDTH = 24


def write_workbook(
    headers: Sequence[str],
    rows: Sequence[Mapping[str, str]],
    dest: Path | str,
    *,
    sheet_name: str = "data",
    column_widths: Mapping[str, int] | None = None,
    metadata: Mapping[str, str] | None = None,
) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    widths = column_widths or {}

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = sheet_name

    sheet.append(list(headers))
    for cell in sheet[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(vertical="top")

    for row in rows:
        sheet.append([_clip(str(row.get(header, "") or "")) for header in headers])

    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{max(sheet.max_row, 1)}"
    for index, header in enumerate(headers, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = widths.get(header, _DEFAULT_WIDTH)

    if metadata:
        info = workbook.create_sheet("info")
        info.append(["campo", "valor"])
        for cell in info[1]:
            cell.font = Font(bold=True)
        for key, value in metadata.items():
            info.append([key, str(value)])
        info.column_dimensions["A"].width = 22
        info.column_dimensions["B"].width = 90

    workbook.save(dest)
    return dest


def _clip(value: str) -> str:
    if len(value) <= _MAX_CELL:
        return value
    return value[: _MAX_CELL - 1] + "…"
