"""Flat-sheet schema for the OFAC SDN export.

``COLUMNS`` pairs each :class:`~.parser.PartyRecord` attribute with its output
header (kept in Portuguese to match the rest of the deliverable).
"""

from __future__ import annotations

COLUMNS: list[tuple[str, str]] = [
    ("fixed_ref", "id_ofac"),
    ("party_type", "tipo"),
    ("primary_name", "nome_principal"),
    ("aliases", "nomes_alternativos"),
    ("birth_dates", "data_nascimento"),
    ("birth_places", "local_nascimento"),
    ("nationalities", "nacionalidades"),
    ("citizenships", "cidadanias"),
    ("genders", "genero"),
    ("titles", "titulos"),
    ("address_countries", "paises"),
    ("addresses", "enderecos"),
    ("documents", "documentos"),
    ("programs", "programas"),
    ("sanctions_lists", "listas"),
    ("listed_on", "data_listagem"),
    ("emails", "emails"),
    ("websites", "websites"),
    ("crypto_addresses", "enderecos_cripto"),
    ("other_features", "outras_caracteristicas"),
]

HEADERS: list[str] = [header for _, header in COLUMNS]

COLUMN_WIDTHS: dict[str, int] = {
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
