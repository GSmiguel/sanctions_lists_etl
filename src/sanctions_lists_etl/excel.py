"""Write the flattened SDN rows to a single-sheet Excel workbook."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

from .parser import COLUMNS

# Excel's hard limit is 32,767 characters per cell.
_MAX_CELL = 32_000
_SHEET_NAME = "SDN"

_COLUMN_WIDTHS = {
    "id_ofac": 10,
    "tipo": 12,
    "nome_principal": 40,
    "nomes_alternativos": 60,
    "data_nascimento": 16,
    "local_nascimento": 30,
    "nacionalidades": 20,
    "cidadanias": 20,
    "genero": 10,
    "titulos": 30,
    "paises": 24,
    "enderecos": 60,
    "documentos": 50,
    "programas": 24,
    "listas": 16,
    "data_listagem": 14,
    "emails": 30,
    "websites": 30,
    "enderecos_cripto": 40,
    "outras_caracteristicas": 60,
}


def write_workbook(
    rows: Sequence[dict[str, str]],
    dest: Path | str,
    *,
    metadata: dict[str, str] | None = None,
) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    headers = [header for _, header in COLUMNS]

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = _SHEET_NAME

    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(vertical="top")

    for row in rows:
        sheet.append([_clip(row.get(header, "")) for header in headers])

    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = (
        f"A1:{get_column_letter(len(headers))}{max(sheet.max_row, 1)}"
    )
    for index, header in enumerate(headers, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = _COLUMN_WIDTHS.get(header, 24)

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
