"""Tests for the shared build_rows / resolve_input skeleton."""

from __future__ import annotations

from dataclasses import dataclass, field

from sanctions_lists_etl.common.download import FetchResult
from sanctions_lists_etl.common.pipeline import (
    Provenance,
    SourceSpec,
    build_rows,
    resolve_input,
)

_COLUMNS = [("ref", "ref"), ("party_type", "type"), ("aka", "aka")]


@dataclass
class _Party:
    ref: str
    party_type: str = "Individual"
    aka: list[str] = field(default_factory=list)

    def to_row(self):
        from sanctions_lists_etl.common.records import flatten_row

        return flatten_row(self, _COLUMNS)


def _parse(content, **_):
    # two rows, deliberately out of order
    return [_Party("Z9", "Entity"), _Party("A1", "Individual", ["x", "x"])]


_SPEC = SourceSpec(
    name="demo",
    description="Demo source",
    raw_filename="demo.xml",
    parse=_parse,
    rows_from_records=lambda records: [r.to_row() for r in records],
    sort_key=lambda r: r.ref,
)


def test_build_rows_sorts_counts_and_flattens():
    build = build_rows(
        _SPEC,
        content=b"<x/>",
        provenance=Provenance("demo.xml", "abc123", "https://example.test/demo.xml"),
        extra_metadata={"note": "hi"},
    )

    assert [r["ref"] for r in build.rows] == ["A1", "Z9"]  # sorted
    assert build.counts_by_type == {"Individual": 1, "Entity": 1}
    assert build.metadata["source_sha256"] == "abc123"
    assert build.metadata["count_individual"] == "1"
    assert build.metadata["note"] == "hi"
    assert build.record_count == 2


def test_to_source_result_carries_counts():
    build = build_rows(_SPEC, content=b"<x/>", provenance=Provenance("demo.xml", "", ""))
    result = build.to_source_result()

    assert result.source == "demo"
    assert result.record_count == 2
    assert result.counts_by_type == build.counts_by_type


def test_resolve_input_prefers_local_file(tmp_path):
    local = tmp_path / "given.xml"
    local.write_text("<x/>")

    def _fetch():  # pragma: no cover - must not be called
        raise AssertionError("fetch called for a local file")

    content, provenance = resolve_input(_SPEC, fetch=_fetch, local_path=local)
    assert content == b"<x/>"
    assert provenance.source_file == "given.xml"
    assert provenance.source_sha256  # computed locally, not read from a sidecar


def test_resolve_input_downloads_when_no_local_path():
    result = FetchResult(
        b"<x/>", "deadbeef", 4, "2026-01-01T00:00:00+00:00", "https://x.test/demo.xml"
    )

    content, provenance = resolve_input(_SPEC, fetch=lambda: result, local_path=None)
    assert content == b"<x/>"
    assert provenance.source_sha256 == "deadbeef"
    assert provenance.source_file == "demo.xml"  # spec's raw_filename label


def test_resolve_input_redacts_downloaded_url_when_spec_asks():
    url = "https://example.test/demo.xml?token=zzz"
    result = FetchResult(b"<x/>", "deadbeef", 4, "2026-01-01T00:00:00+00:00", url)
    spec = SourceSpec(**{**_SPEC.__dict__, "redact_url": lambda u: u.split("?")[0]})

    _, provenance = resolve_input(spec, fetch=lambda: result, local_path=None)
    assert "zzz" not in provenance.source_url
