"""Flat row schema for the UN Security Council Consolidated List.

``COLUMNS`` pairs each :class:`~.parser.SanctionParty` attribute with its output
header.  Headers line up with the OFAC SDN export
(:mod:`sanctions_lists_etl.sources.ofac.columns`) and the EU FSF export
(:mod:`sanctions_lists_etl.sources.eu.columns`) wherever the three lists carry
the same information, so they can be compared side by side.

UN-specific swaps: ``un_reference_number`` / ``data_id`` replace ``ofac_id``,
``un_list_type`` fills the ``programmes`` slot (the sanctions committee / regime,
e.g. Al-Qaida, Taliban, DPRK), and it adds ``name_original_script``,
``last_updated``, ``last_reviewed_on`` and ``interpol_notice``.
"""

from __future__ import annotations

COLUMNS: list[tuple[str, str]] = [
    ("un_reference_number", "un_reference_number"),
    ("data_id", "data_id"),
    ("party_type", "type"),
    ("primary_name", "primary_name"),
    ("name_original_script", "name_original_script"),
    ("aliases", "aliases"),
    ("birth_dates", "dates_of_birth"),
    ("birth_places", "places_of_birth"),
    ("nationalities", "nationalities"),
    ("genders", "gender"),
    ("titles", "titles"),
    ("designations", "functions"),
    ("address_countries", "countries"),
    ("addresses", "addresses"),
    ("documents", "id_documents"),
    ("un_list_type", "programmes"),
    ("sanctions_lists", "lists"),
    ("listed_on", "listed_on"),
    ("last_updated", "last_updated"),
    ("last_reviewed_on", "last_reviewed_on"),
    ("interpol_notice", "interpol_notice"),
    ("comments", "remarks"),
]
