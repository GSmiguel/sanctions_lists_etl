"""Flat row schema for the UK Sanctions List (FCDO).

``COLUMNS`` pairs each :class:`~.parser.SanctionParty` attribute with its output
header.  Headers line up with the OFAC SDN, EU FSF and UN Consolidated exports
wherever the lists carry the same information, so they can be compared side by
side.

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
