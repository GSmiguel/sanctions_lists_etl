"""Flat-sheet schema for the OFAC SDN export.

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

HEADERS: list[str] = [header for _, header in COLUMNS]

COLUMN_WIDTHS: dict[str, int] = {
    "ofac_id": 10,
    "type": 12,
    "primary_name": 40,
    "aliases": 60,
    "dates_of_birth": 16,
    "places_of_birth": 30,
    "nationalities": 20,
    "citizenships": 20,
    "gender": 10,
    "titles": 30,
    "countries": 24,
    "addresses": 60,
    "id_documents": 50,
    "programs": 24,
    "lists": 16,
    "listed_on": 14,
    "emails": 30,
    "websites": 30,
    "digital_currency_addresses": 40,
    "other_features": 60,
}
