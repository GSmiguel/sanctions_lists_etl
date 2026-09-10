"""Flatten an INTERPOL UN Special Notice snapshot (JSON) into :class:`Notice` rows.

The snapshot written by :mod:`.download` is a JSON array of **summary** rows, each
tagged with a private ``_notice_kind`` (``"un-person"`` or ``"un-entity"``).
Summary rows are thin — id, name, date of birth, ``un_reference`` and the notice /
image links — so parsing is a plain dict walk with no reference tables.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

log = logging.getLogger(__name__)

from .columns import COLUMNS

_LIST_SEP = "; "

_NOTICE_TYPE = "UN Special Notice"
_ENTITY_KINDS = {"un-entity"}


@dataclass
class Notice:
    interpol_notice_id: str
    un_reference: str = ""
    party_type: str = "Individual"
    primary_name: str = ""
    birth_dates: list[str] = field(default_factory=list)
    notice_type: str = _NOTICE_TYPE
    notice_url: str = ""
    image_url: str = ""

    def to_row(self) -> dict[str, str]:
        row: dict[str, str] = {}
        for attr, header in COLUMNS:
            value = getattr(self, attr)
            if isinstance(value, list):
                seen: list[str] = []
                for item in value:
                    if item and item not in seen:
                        seen.append(item)
                row[header] = _LIST_SEP.join(seen)
            else:
                row[header] = value or ""
        return row


def parse_interpol(source: Path | str) -> list[Notice]:
    """Parse ``source`` and return one :class:`Notice` per UN Special Notice."""
    raw = json.loads(Path(source).read_text(encoding="utf-8"))
    records = [_build_notice(obj) for obj in raw]
    log.info("parsed %d notices", len(records))
    return records


def rows_from_records(records: Iterable[Notice]) -> list[dict[str, str]]:
    return [record.to_row() for record in records]


# --------------------------------------------------------------------------- #
def _build_notice(obj: dict[str, Any]) -> Notice:
    kind = obj.get("_notice_kind", "un-person")
    record = Notice(
        interpol_notice_id=str(obj.get("entity_id") or "").strip(),
        un_reference=str(obj.get("un_reference") or "").strip(),
        party_type="Entity" if kind in _ENTITY_KINDS else "Individual",
        primary_name=_person_name(obj.get("name"), obj.get("forename")),
    )

    born = _iso_date(obj.get("date_of_birth"))
    if born:
        record.birth_dates.append(born)

    links = obj.get("_links") or {}
    record.notice_url = _href(links.get("self"))
    record.image_url = _href(links.get("images")) or _href(links.get("thumbnail"))
    return record


def _person_name(name: Any, forename: Any) -> str:
    """Render a name surname-first (``SURNAME, Forename``), matching the OFAC export."""
    surname = (name or "").strip()
    given = (forename or "").strip()
    if surname and given:
        return f"{surname}, {given}"
    return surname or given


def _iso_date(value: Any) -> str:
    """``"1990/08/07"`` -> ``"1990-08-07"``; zero month/day are dropped."""
    text = (value or "").strip()
    if not text:
        return ""
    parts = text.replace("-", "/").split("/")
    if not parts or not parts[0].isdigit() or parts[0] in ("0", "0000"):
        return ""
    out = parts[0].zfill(4)
    for part in parts[1:]:
        if part.isdigit() and int(part) > 0:
            out += f"-{int(part):02d}"
        else:
            break
    return out


def _href(link: Any) -> str:
    if isinstance(link, dict):
        return (link.get("href") or "").strip()
    return ""
