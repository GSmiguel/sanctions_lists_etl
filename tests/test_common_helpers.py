"""Tests for the shared row-flattening and reference-sort helpers."""

from __future__ import annotations

from dataclasses import dataclass, field

from sanctions_lists_etl.common.records import flatten_row
from sanctions_lists_etl.common.sortkeys import reference_sort_key

_COLUMNS = [("ref", "ref"), ("names", "names"), ("note", "note")]


@dataclass
class _Rec:
    ref: str = ""
    names: list[str] = field(default_factory=list)
    note: str | None = None


def test_flatten_row_joins_dedupes_and_drops_blanks():
    row = flatten_row(_Rec(ref="A1", names=["Bob", "", "Bob", "Bobby"], note=None), _COLUMNS)
    assert row == {"ref": "A1", "names": "Bob; Bobby", "note": ""}


def test_flatten_row_keys_are_exactly_the_headers():
    row = flatten_row(_Rec(), _COLUMNS)
    assert set(row) == {"ref", "names", "note"}


def test_reference_sort_key_orders_numerically_within_a_prefix():
    refs = ["QDi.100", "QDi.9", "QDi.11"]
    assert sorted(refs, key=reference_sort_key) == ["QDi.9", "QDi.11", "QDi.100"]


def test_reference_sort_key_splits_prefix_and_numbers():
    assert reference_sort_key("EU.27.28") == ("EU", (27, 28), "EU.27.28")
    assert reference_sort_key("12345") == ("", (12345,), "12345")
    assert reference_sort_key("RUS0123") == ("RUS", (123,), "RUS0123")


def test_reference_sort_key_puts_bare_numbers_before_lettered_refs():
    refs = ["abc", "12345", "RUS1"]
    assert sorted(refs, key=reference_sort_key)[0] == "12345"
