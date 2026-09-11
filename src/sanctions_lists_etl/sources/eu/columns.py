"""Flat row schema for the EU consolidated sanctions list.

``COLUMNS`` pairs each :class:`~.parser.SanctionEntity` attribute with its output
header.  Column names line up with the OFAC SDN export
(:mod:`sanctions_lists_etl.sources.ofac.columns`) wherever the two lists carry
the same information, so the two can be compared side by side.
"""

from __future__ import annotations

COLUMNS: list[tuple[str, str]] = [
    ("eu_reference_number", "eu_reference_number"),
    ("un_id", "un_id"),
    ("party_type", "type"),
    ("primary_name", "primary_name"),
    ("aliases", "aliases"),
    ("birth_dates", "dates_of_birth"),
    ("birth_places", "places_of_birth"),
    ("citizenships", "citizenships"),
    ("genders", "gender"),
    ("titles", "titles"),
    ("functions", "functions"),
    ("address_countries", "countries"),
    ("addresses", "addresses"),
    ("documents", "id_documents"),
    ("programmes", "programmes"),
    ("regulations", "regulations"),
    ("listed_on", "listed_on"),
    ("emails", "emails"),
    ("phones", "phones"),
    ("websites", "websites"),
    ("remarks", "remarks"),
]
