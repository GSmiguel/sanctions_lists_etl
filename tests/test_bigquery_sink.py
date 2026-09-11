"""Tests for the BigQuery sink — no real GCP calls, a fake ``Client``.

``google.cloud.bigquery``'s own value objects (``QueryJobConfig``,
``ScalarQueryParameter``, ``SchemaField``, the write-disposition enums) are used
for real — they're pure Python, no network — only ``Client`` (which does I/O) is
replaced. Skipped entirely when the optional ``bigquery`` extra isn't installed.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import pytest

bigquery = pytest.importorskip("google.cloud.bigquery")

from sanctions_lists_etl.common.pipeline import BuildResult, Provenance, SourceSpec
from sanctions_lists_etl.common.sinks.bigquery import BigQuerySink, load_bigquery, normalized_rows


@dataclass
class _Record:
    ref: str
    name: str
    party_type: str = "Individual"


def _to_normalized(record, *, source_key, snapshot_date, source_sha256, ingested_at):
    return {
        "snapshot_date": snapshot_date,
        "source": source_key,
        "source_authority": "TEST",
        "source_reference": record.ref,
        "uid": f"{source_key}:{record.ref}",
        "party_type": record.party_type,
        "primary_name": record.name,
        "source_sha256": source_sha256,
        "ingested_at": ingested_at,
    }


_SPEC = SourceSpec(
    name="demo",
    description="Demo",
    raw_filename="demo.xml",
    parse=lambda p, **_: [],
    rows_from_records=lambda records: [],
    sort_key=lambda r: r.ref,
)


def _build(*, records=None) -> BuildResult:
    records = records if records is not None else [_Record("A1", "Alice"), _Record("B2", "Bob")]
    return BuildResult(
        spec=_SPEC,
        records=records,
        rows=[],
        counts_by_type={},
        metadata={},
        provenance=Provenance(source_file="demo.xml", source_sha256="abc123", source_url=""),
    )


class _FakeJob:
    def result(self):
        return None


@dataclass
class _FakeClient:
    queries: list = field(default_factory=list)
    loads: list = field(default_factory=list)

    def query(self, sql, job_config=None):
        params = {p.name: p.value for p in (job_config.query_parameters if job_config else [])}
        self.queries.append((sql, params))
        return _FakeJob()

    def load_table_from_json(self, rows, table_id, job_config=None):
        self.loads.append((list(rows), table_id, job_config))
        return _FakeJob()


def test_normalized_rows_carries_provenance_sha256():
    build = _build()
    rows = normalized_rows(
        build,
        _to_normalized,
        source_key="demo_src",
        snapshot_date="2026-01-01",
        ingested_at="2026-01-01T00:00:00+00:00",
    )
    assert [r["uid"] for r in rows] == ["demo_src:A1", "demo_src:B2"]
    assert all(r["source_sha256"] == "abc123" for r in rows)


def test_sink_load_deletes_then_appends_and_updates_manifest():
    client = _FakeClient()
    sink = BigQuerySink(project="proj", dataset="sanctions", client=client)
    rows = [{"uid": "demo_src:A1"}]

    outcome = sink.load(rows, source_key="demo_src", snapshot_date="2026-01-01")

    assert outcome.status == "loaded"
    assert outcome.row_count == 1
    assert len(client.queries) == 2  # DELETE, then the manifest MERGE
    delete_sql, delete_params = client.queries[0]
    assert "DELETE FROM" in delete_sql
    # bigquery.ScalarQueryParameter coerces a DATE-typed value into a real date.
    assert delete_params == {"snapshot_date": dt.date(2026, 1, 1), "source": "demo_src"}
    assert "MERGE" in client.queries[1][0]
    assert len(client.loads) == 1
    loaded_rows, table_id, job_config = client.loads[0]
    assert loaded_rows == rows
    assert table_id == "proj.sanctions.entries"
    assert job_config.write_disposition == bigquery.WriteDisposition.WRITE_APPEND


def test_sink_load_skips_when_no_rows():
    client = _FakeClient()
    sink = BigQuerySink(project="proj", client=client)

    outcome = sink.load([], source_key="demo_src", snapshot_date="2026-01-01")

    assert outcome.status == "skipped (no rows)"
    assert not client.queries
    assert not client.loads


def test_load_bigquery_loads_every_run_and_records_metadata():
    build = _build()
    client = _FakeClient()

    outcome = load_bigquery(
        build, _to_normalized, source_key="demo_src", project="proj", client=client
    )

    assert outcome.status == "loaded"
    assert outcome.row_count == 2
    assert client.loads
    assert "loaded" in build.metadata["bigquery"]
