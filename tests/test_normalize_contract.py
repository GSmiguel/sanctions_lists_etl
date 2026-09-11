"""Cross-source contract checks for the BigQuery normalization layer.

Mirrors ``test_contract.py``'s approach for the Excel export: pin that every
source's ``to_normalized`` stays inside ``common.schema.ENTRIES_FIELDS`` and
fills every ``REQUIRED`` field, so a schema/mapping drift fails a fast local
test instead of a load job in production.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, NamedTuple

import pytest

from sanctions_lists_etl.common.schema import FIELD_NAMES, REQUIRED_FIELDS
from sanctions_lists_etl.sources.eu.normalize import to_normalized as eu_to_normalized
from sanctions_lists_etl.sources.eu.parser import parse_eu_fsf
from sanctions_lists_etl.sources.ofac.normalize import to_normalized as ofac_to_normalized
from sanctions_lists_etl.sources.ofac.parser import parse_sdn_advanced
from sanctions_lists_etl.sources.uk.normalize import to_normalized as uk_to_normalized
from sanctions_lists_etl.sources.uk.parser import parse_uk_sanctions
from sanctions_lists_etl.sources.un.normalize import to_normalized as un_to_normalized
from sanctions_lists_etl.sources.un.parser import parse_un_consolidated

_SNAPSHOT_DATE = "2026-01-01"
_SOURCE_SHA256 = "deadbeef"
_INGESTED_AT = "2026-01-01T00:00:00+00:00"


class Contract(NamedTuple):
    name: str
    source_key: str
    parse: Callable[[Any], list]
    to_normalized: Callable[..., dict]
    fixture: str


CONTRACTS: list[Contract] = [
    Contract("ofac", "ofac_sdn", parse_sdn_advanced, ofac_to_normalized, "sample_xml"),
    Contract("eu", "eu_fsf", parse_eu_fsf, eu_to_normalized, "sample_eu_xml"),
    Contract("un", "un_sc", parse_un_consolidated, un_to_normalized, "sample_un_xml"),
    Contract("uk", "uk_fcdo", parse_uk_sanctions, uk_to_normalized, "sample_uk_xml"),
]

_IDS = [c.name for c in CONTRACTS]


def _rows(contract: Contract, request) -> list[dict]:
    sample = request.getfixturevalue(contract.fixture)
    records = contract.parse(sample)
    assert records, f"{contract.name}: fixture produced no records"
    return [
        contract.to_normalized(
            record,
            source_key=contract.source_key,
            snapshot_date=_SNAPSHOT_DATE,
            source_sha256=_SOURCE_SHA256,
            ingested_at=_INGESTED_AT,
        )
        for record in records
    ]


@pytest.mark.parametrize("contract", CONTRACTS, ids=_IDS)
def test_rows_stay_inside_the_schema(contract: Contract, request):
    for row in _rows(contract, request):
        unknown = set(row) - FIELD_NAMES
        assert not unknown, f"{contract.name}: fields not in ENTRIES_FIELDS: {unknown}"


@pytest.mark.parametrize("contract", CONTRACTS, ids=_IDS)
def test_required_fields_are_filled(contract: Contract, request):
    for row in _rows(contract, request):
        for field in REQUIRED_FIELDS:
            assert row.get(field), f"{contract.name}: required field {field!r} is empty in {row}"


@pytest.mark.parametrize("contract", CONTRACTS, ids=_IDS)
def test_uid_is_unique_and_source_scoped(contract: Contract, request):
    rows = _rows(contract, request)
    uids = [row["uid"] for row in rows]
    assert len(uids) == len(set(uids)), f"{contract.name}: duplicate uid"
    assert all(uid.startswith(f"{contract.source_key}:") for uid in uids)


@pytest.mark.parametrize("contract", CONTRACTS, ids=_IDS)
def test_array_fields_are_lists_of_str(contract: Contract, request):
    array_fields = {"aliases", "birth_dates", "documents", "listed_on"}
    for row in _rows(contract, request):
        for field in array_fields:
            assert isinstance(row[field], list), f"{contract.name}: {field} is not a list"
            assert all(isinstance(item, str) for item in row[field])
