"""Tests for the shared build_rows / resolve_input skeleton."""

from __future__ import annotations

from dataclasses import dataclass, field

from sanctions_lists_etl.common.download import FetchResult
from sanctions_lists_etl.common.meta import write_meta
from sanctions_lists_etl.common.pipeline import (
    Provenance,
    SourceSpec,
    build_rows,
    resolve_input,
    write_excel,
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


def _parse(path, **_):
    # two rows, deliberately out of order
    return [_Party("Z9", "Entity"), _Party("A1", "Individual", ["x", "x"])]


_SPEC = SourceSpec(
    name="demo",
    description="Demo source",
    raw_filename="demo.xml",
    output_filename="demo.xlsx",
    sheet_name="DEMO",
    headers=["ref", "type", "aka"],
    column_widths={},
    parse=_parse,
    rows_from_records=lambda records: [r.to_row() for r in records],
    sort_key=lambda r: r.ref,
)


def test_build_rows_sorts_counts_and_flattens(tmp_path):
    src = tmp_path / "demo.xml"
    src.write_text("<x/>")
    build = build_rows(
        _SPEC,
        source_path=src,
        provenance=Provenance("demo.xml", "abc123", "https://example.test/demo.xml"),
        extra_metadata={"note": "hi"},
    )

    assert [r["ref"] for r in build.rows] == ["A1", "Z9"]  # sorted
    assert build.counts_by_type == {"Individual": 1, "Entity": 1}
    assert build.metadata["source_sha256"] == "abc123"
    assert build.metadata["count_individual"] == "1"
    assert build.metadata["note"] == "hi"
    assert build.record_count == 2


def test_to_source_result_carries_outputs(tmp_path):
    src = tmp_path / "demo.xml"
    src.write_text("<x/>")
    build = build_rows(_SPEC, source_path=src, provenance=Provenance("demo.xml", "", ""))
    dest = write_excel(build, tmp_path)
    result = build.to_source_result([dest])

    assert result.source == "demo"
    assert result.xlsx_path == dest
    assert result.outputs == [dest]
    assert dest.exists()


def test_resolve_input_prefers_local_file(tmp_path):
    local = tmp_path / "given.xml"
    local.write_text("<x/>")

    def _fetch():  # pragma: no cover - must not be called
        raise AssertionError("fetch called for a local file")

    path, provenance = resolve_input(
        _SPEC, raw_dir=tmp_path, fetch=_fetch, local_path=local, download=True
    )
    assert path == local
    assert provenance.source_file == "given.xml"


def test_resolve_input_uses_cache_when_download_is_off(tmp_path):
    cached = tmp_path / "demo.xml"
    cached.write_text("<x/>")
    write_meta(cached, {"sha256": "cafe", "url": "https://example.test/demo.xml"})

    def _fetch():  # pragma: no cover
        raise AssertionError("fetch called with download=False and a cache present")

    path, provenance = resolve_input(
        _SPEC, raw_dir=tmp_path, fetch=_fetch, local_path=None, download=False
    )
    assert path == cached
    assert provenance.source_sha256 == "cafe"


def test_resolve_input_downloads_when_asked(tmp_path):
    produced = tmp_path / "demo.xml"
    produced.write_text("<x/>")
    result = FetchResult(
        produced, "deadbeef", 4, "2026-01-01T00:00:00+00:00", "https://x.test/demo.xml"
    )

    path, provenance = resolve_input(
        _SPEC, raw_dir=tmp_path, fetch=lambda: result, local_path=None, download=True
    )
    assert path == produced
    assert provenance.source_sha256 == "deadbeef"
    assert provenance.not_modified is False


def test_resolve_input_redacts_cached_url_when_spec_asks(tmp_path):
    cached = tmp_path / "demo.xml"
    cached.write_text("<x/>")
    write_meta(cached, {"url": "https://example.test/demo.xml?token=zzz"})
    spec = SourceSpec(**{**_SPEC.__dict__, "redact_url": lambda u: u.split("?")[0]})

    _, provenance = resolve_input(
        spec, raw_dir=tmp_path, fetch=lambda: None, local_path=None, download=False
    )
    assert "zzz" not in provenance.source_url
