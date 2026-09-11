"""Cross-source contract checks.

Every source flattens its own record dataclass into ``dict[str, str]`` rows keyed
by the headers in its ``columns`` module.  A column/attribute mismatch
introduced by a refactor would not fail a parser test — it would just surface
as a missing/blank column downstream.  These tests pin the contract:

* ``COLUMNS`` maps real dataclass attributes to unique headers;
* ``rows_from_records`` emits rows whose keys are exactly those headers.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import Any, NamedTuple

import pytest

from sanctions_lists_etl.sources.eu import columns as eu_columns
from sanctions_lists_etl.sources.eu import parser as eu_parser
from sanctions_lists_etl.sources.ofac import columns as ofac_columns
from sanctions_lists_etl.sources.ofac import parser as ofac_parser
from sanctions_lists_etl.sources.uk import columns as uk_columns
from sanctions_lists_etl.sources.uk import parser as uk_parser
from sanctions_lists_etl.sources.un import columns as un_columns
from sanctions_lists_etl.sources.un import parser as un_parser


class Contract(NamedTuple):
    name: str
    record_cls: type
    columns: list[tuple[str, str]]
    parse: Callable[[Any], list]
    rows_from_records: Callable[[list], list[dict[str, str]]]
    fixture: str  # conftest fixture name for the sample file


CONTRACTS: list[Contract] = [
    Contract(
        "ofac",
        ofac_parser.PartyRecord,
        ofac_columns.COLUMNS,
        ofac_parser.parse_sdn_advanced,
        ofac_parser.rows_from_records,
        "sample_xml",
    ),
    Contract(
        "eu",
        eu_parser.SanctionEntity,
        eu_columns.COLUMNS,
        eu_parser.parse_eu_fsf,
        eu_parser.rows_from_records,
        "sample_eu_xml",
    ),
    Contract(
        "un",
        un_parser.SanctionParty,
        un_columns.COLUMNS,
        un_parser.parse_un_consolidated,
        un_parser.rows_from_records,
        "sample_un_xml",
    ),
    Contract(
        "uk",
        uk_parser.SanctionParty,
        uk_columns.COLUMNS,
        uk_parser.parse_uk_sanctions,
        uk_parser.rows_from_records,
        "sample_uk_xml",
    ),
]

_IDS = [c.name for c in CONTRACTS]


@pytest.mark.parametrize("contract", CONTRACTS, ids=_IDS)
def test_columns_map_real_attributes_to_unique_headers(contract: Contract):
    attrs = {f.name for f in dataclasses.fields(contract.record_cls)}
    col_attrs = [attr for attr, _ in contract.columns]
    col_headers = [header for _, header in contract.columns]

    unknown = [a for a in col_attrs if a not in attrs]
    assert not unknown, f"{contract.name}: COLUMNS references unknown attributes {unknown}"
    assert len(col_headers) == len(set(col_headers)), f"{contract.name}: duplicate headers"


@pytest.mark.parametrize("contract", CONTRACTS, ids=_IDS)
def test_rows_have_exactly_the_declared_headers(contract: Contract, request):
    sample = request.getfixturevalue(contract.fixture)
    rows = contract.rows_from_records(contract.parse(sample.read_bytes()))
    assert rows, f"{contract.name}: fixture produced no rows"
    want = {header for _, header in contract.columns}
    for row in rows:
        assert set(row) == want, f"{contract.name}: row keys {set(row) ^ want} differ from headers"
