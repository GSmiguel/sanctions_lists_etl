"""Flat-sheet schema for the UK Sanctions List (FCDO).

``COLUMNS`` pairs each :class:`~.parser.SanctionParty` attribute with its output
header.  Headers line up with the OFAC SDN, EU FSF and UN Consolidated exports
wherever the lists carry the same information, so the workbooks can be compared
side by side.

UK-specific swaps: ``uk_unique_id`` / ``ofsi_group_id`` replace ``ofac_id``,
``un_reference_number`` cross-refs the UN list, ``programmes`` holds the UK
sanctions regime (``RegimeName``), and it adds ``designation_source``,
``sanctions_imposed``, ``name_original_script``, ``last_updated``,
``entity_type`` / ``parent_companies`` / ``subsidiaries``, ``vessel_info`` and
``statement_of_reasons``.
"""

from __future__ import annotations

COLUMNS: list[tuple[str, str]] = [
    ("uk_unique_id", "uk_unique_id"),
    ("ofsi_group_id", "ofsi_group_id"),
    ("un_reference_number", "un_reference_number"),
    ("party_type", "type"),
    ("primary_name", "primary_name"),
    ("name_original_script", "name_original_script"),
    ("aliases", "aliases"),
    ("titles", "titles"),
    ("birth_dates", "dates_of_birth"),
    ("birth_places", "places_of_birth"),
    ("nationalities", "nationalities"),
    ("genders", "gender"),
    ("positions", "functions"),
    ("address_countries", "countries"),
    ("addresses", "addresses"),
    ("documents", "id_documents"),
    ("regime_name", "programmes"),
    ("designation_source", "designation_source"),
    ("sanctions_imposed", "sanctions_imposed"),
    ("listed_on", "listed_on"),
    ("last_updated", "last_updated"),
    ("phones", "phones"),
    ("emails", "emails"),
    ("websites", "websites"),
    ("entity_type", "entity_type"),
    ("parent_companies", "parent_companies"),
    ("subsidiaries", "subsidiaries"),
    ("vessel_info", "vessel_info"),
    ("statement_of_reasons", "statement_of_reasons"),
    ("other_information", "remarks"),
]

HEADERS: list[str] = [header for _, header in COLUMNS]

COLUMN_WIDTHS: dict[str, int] = {
    "uk_unique_id": 14,
    "ofsi_group_id": 12,
    "un_reference_number": 16,
    "type": 12,
    "primary_name": 40,
    "name_original_script": 30,
    "aliases": 60,
    "titles": 20,
    "dates_of_birth": 18,
    "places_of_birth": 30,
    "nationalities": 20,
    "gender": 10,
    "functions": 40,
    "countries": 24,
    "addresses": 60,
    "id_documents": 50,
    "programmes": 44,
    "designation_source": 16,
    "sanctions_imposed": 26,
    "listed_on": 14,
    "last_updated": 14,
    "phones": 22,
    "emails": 28,
    "websites": 28,
    "entity_type": 24,
    "parent_companies": 30,
    "subsidiaries": 30,
    "vessel_info": 50,
    "statement_of_reasons": 70,
    "remarks": 70,
}
