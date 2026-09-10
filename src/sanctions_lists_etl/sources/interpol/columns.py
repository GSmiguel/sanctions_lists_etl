"""Flat-sheet schema for the INTERPOL notices export.

``COLUMNS`` pairs each :class:`~.parser.Notice` attribute with its output header.
Headers line up with the OFAC SDN / EU FSF / UN exports wherever the lists carry
the same information (``type``, ``primary_name``, ``aliases``, ``dates_of_birth``,
``places_of_birth``, ``nationalities``, ``gender``, ``id_documents``,
``listed_on``, ``remarks``), so the workbooks can be compared side by side.

INTERPOL-specific swaps: ``interpol_notice_id`` replaces ``ofac_id``, and the
list adds ``notice_type`` (Red Notice / UN Special Notice), ``un_reference``
(the UN designation reference on a Special Notice), ``charges`` +
``warrant_countries`` (the arrest-warrant text and the countries that issued
it), ``languages_spoken``, ``physical_description``, ``notice_url`` and
``image_url``.
"""

from __future__ import annotations

COLUMNS: list[tuple[str, str]] = [
    ("interpol_notice_id", "interpol_notice_id"),
    ("notice_type", "notice_type"),
    ("un_reference", "un_reference"),
    ("party_type", "type"),
    ("primary_name", "primary_name"),
    ("aliases", "aliases"),
    ("birth_dates", "dates_of_birth"),
    ("birth_places", "places_of_birth"),
    ("nationalities", "nationalities"),
    ("genders", "gender"),
    ("charges", "charges"),
    ("warrant_countries", "warrant_countries"),
    ("documents", "id_documents"),
    ("languages_spoken", "languages_spoken"),
    ("physical_description", "physical_description"),
    ("listed_on", "listed_on"),
    ("notice_url", "notice_url"),
    ("image_url", "image_url"),
    ("summary", "remarks"),
]

HEADERS: list[str] = [header for _, header in COLUMNS]

COLUMN_WIDTHS: dict[str, int] = {
    "interpol_notice_id": 16,
    "notice_type": 20,
    "un_reference": 14,
    "type": 12,
    "primary_name": 40,
    "aliases": 50,
    "dates_of_birth": 18,
    "places_of_birth": 34,
    "nationalities": 22,
    "gender": 10,
    "charges": 70,
    "warrant_countries": 22,
    "id_documents": 44,
    "languages_spoken": 22,
    "physical_description": 34,
    "listed_on": 14,
    "notice_url": 46,
    "image_url": 46,
    "remarks": 70,
}
