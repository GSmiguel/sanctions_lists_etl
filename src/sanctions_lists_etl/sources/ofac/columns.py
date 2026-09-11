"""Flat row schema for the OFAC SDN export.

``COLUMNS`` pairs each :class:`~.parser.PartyRecord` attribute with its output
header.
"""

from __future__ import annotations

COLUMNS: list[tuple[str, str]] = [
    ("fixed_ref", "ofac_id"),
    ("party_type", "type"),
    ("primary_name", "primary_name"),
    ("aliases", "aliases"),
    ("birth_dates", "dates_of_birth"),
    ("birth_places", "places_of_birth"),
    ("nationalities", "nationalities"),
    ("citizenships", "citizenships"),
    ("genders", "gender"),
    ("titles", "titles"),
    ("address_countries", "countries"),
    ("addresses", "addresses"),
    ("documents", "id_documents"),
    ("programs", "programs"),
    ("sanctions_lists", "lists"),
    ("listed_on", "listed_on"),
    ("emails", "emails"),
    ("websites", "websites"),
    ("crypto_addresses", "digital_currency_addresses"),
    ("other_features", "other_features"),
]
