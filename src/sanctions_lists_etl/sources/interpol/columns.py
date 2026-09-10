"""Flat-sheet schema for the INTERPOL UN Special Notice export.

``COLUMNS`` pairs each :class:`~.parser.Notice` attribute with its output header.
The list is thin because only the notices' summary rows are pulled (see
:mod:`.download`): `type`, `primary_name` and `dates_of_birth` line up with the
OFAC / EU / UN exports; `interpol_notice_id` replaces `ofac_id`; `un_reference`
ties the row back to the UN Consolidated List (stage 3); `notice_type`,
`notice_url` and `image_url` are INTERPOL-specific.
"""

from __future__ import annotations

COLUMNS: list[tuple[str, str]] = [
    ("interpol_notice_id", "interpol_notice_id"),
    ("un_reference", "un_reference"),
    ("notice_type", "notice_type"),
    ("party_type", "type"),
    ("primary_name", "primary_name"),
    ("birth_dates", "dates_of_birth"),
    ("notice_url", "notice_url"),
    ("image_url", "image_url"),
]

HEADERS: list[str] = [header for _, header in COLUMNS]

COLUMN_WIDTHS: dict[str, int] = {
    "interpol_notice_id": 16,
    "un_reference": 14,
    "notice_type": 20,
    "type": 12,
    "primary_name": 44,
    "dates_of_birth": 18,
    "notice_url": 50,
    "image_url": 50,
}
