"""BigQuery sink: dated-snapshot load into the unified ``entries`` table.

Delete-then-append per ``(source, snapshot_date)`` — not ``WRITE_TRUNCATE`` on
the whole day-partition.  Sources refresh independently (a run may only fetch a
fresh EU copy while OFAC/UN/UK are unchanged), so a given day's partition ends
up holding rows from several sources landed at different times; truncating the
partition would wipe out whichever source got there first.  This makes a rerun
for the same source/day idempotent without touching anyone else's rows.

``google-cloud-bigquery`` is only imported lazily (inside functions), so this
module — and everything that merely calls :func:`load_bigquery` with
``bigquery=False`` — stays importable without the optional ``bigquery`` extra.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from ..pipeline import BuildResult
from ..schema import DATASET_NAME, ENTRIES_FIELDS, ENTRIES_TABLE, MANIFEST_TABLE

log = logging.getLogger(__name__)

ToNormalized = Callable[..., dict]


def _bigquery_module() -> Any:
    try:
        from google.cloud import bigquery
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise RuntimeError(
            "--bigquery needs the optional dependency: `uv sync --extra bigquery`"
        ) from exc
    return bigquery


def entries_schema() -> list[Any]:
    """The unified table's schema as real ``bigquery.SchemaField`` objects."""
    bigquery = _bigquery_module()
    return [
        bigquery.SchemaField(name, field_type, mode=mode)
        for name, field_type, mode in ENTRIES_FIELDS
    ]


@dataclass(frozen=True)
class LoadOutcome:
    source_key: str
    status: str  # "loaded" | "skipped (no rows)"
    row_count: int = 0

    def __str__(self) -> str:
        return f"{self.status} ({self.row_count} rows)" if self.row_count else self.status


class BigQuerySink:
    """Loads already-normalized rows into ``{project}.{dataset}.entries``."""

    def __init__(self, *, project: str, dataset: str | None = None, client: Any | None = None):
        self.project = project
        self.dataset = dataset or DATASET_NAME
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = _bigquery_module().Client(project=self.project)
        return self._client

    def _table_id(self, table: str) -> str:
        return f"{self.project}.{self.dataset}.{table}"

    def load(self, rows: Sequence[dict], *, source_key: str, snapshot_date: str) -> LoadOutcome:
        if not rows:
            log.info("[bigquery] %s: no rows for %s, nothing to load", source_key, snapshot_date)
            return LoadOutcome(source_key, "skipped (no rows)")

        bigquery = _bigquery_module()
        self._delete_existing(source_key, snapshot_date)

        job_config = bigquery.LoadJobConfig(
            schema=entries_schema(),
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        )
        job = self.client.load_table_from_json(
            list(rows), self._table_id(ENTRIES_TABLE), job_config=job_config
        )
        job.result()
        log.info("[bigquery] %s: loaded %d rows for %s", source_key, len(rows), snapshot_date)
        self._update_manifest(source_key, snapshot_date)
        return LoadOutcome(source_key, "loaded", len(rows))

    def _delete_existing(self, source_key: str, snapshot_date: str) -> None:
        bigquery = _bigquery_module()
        sql = (
            f"DELETE FROM `{self._table_id(ENTRIES_TABLE)}` "
            "WHERE snapshot_date = @snapshot_date AND source = @source"
        )
        self.client.query(
            sql,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("snapshot_date", "DATE", snapshot_date),
                    bigquery.ScalarQueryParameter("source", "STRING", source_key),
                ]
            ),
        ).result()

    def _update_manifest(self, source_key: str, snapshot_date: str) -> None:
        bigquery = _bigquery_module()
        sql = f"""
        MERGE `{self._table_id(MANIFEST_TABLE)}` AS target
        USING (SELECT @source AS source, @snapshot_date AS latest_snapshot_date) AS src
        ON target.source = src.source
        WHEN MATCHED THEN UPDATE SET latest_snapshot_date = src.latest_snapshot_date
        WHEN NOT MATCHED THEN
          INSERT (source, latest_snapshot_date) VALUES (src.source, src.latest_snapshot_date)
        """
        self.client.query(
            sql,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("source", "STRING", source_key),
                    bigquery.ScalarQueryParameter("snapshot_date", "DATE", snapshot_date),
                ]
            ),
        ).result()


def normalized_rows(
    build: BuildResult,
    to_normalized: ToNormalized,
    *,
    source_key: str,
    snapshot_date: str,
    ingested_at: str,
) -> list[dict]:
    return [
        to_normalized(
            record,
            source_key=source_key,
            snapshot_date=snapshot_date,
            source_sha256=build.provenance.source_sha256,
            ingested_at=ingested_at,
        )
        for record in build.records
    ]


def load_bigquery(
    build: BuildResult,
    to_normalized: ToNormalized,
    *,
    source_key: str,
    project: str,
    dataset: str | None = None,
    client: Any | None = None,
) -> LoadOutcome:
    """Load ``build`` into BigQuery.

    Mutates ``build.metadata["bigquery"]`` with a human-readable summary (also
    the return value's ``str()``), so callers get the summary back via
    ``SourceResult.metadata``.  Safe to call on every run: ``BigQuerySink.load``
    deletes then re-appends per ``(source, snapshot_date)``, so a rerun for the
    same source/day is idempotent.
    """
    snapshot_date = dt.datetime.now(dt.UTC).date().isoformat()
    ingested_at = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    rows = normalized_rows(
        build,
        to_normalized,
        source_key=source_key,
        snapshot_date=snapshot_date,
        ingested_at=ingested_at,
    )
    sink = BigQuerySink(project=project, dataset=dataset, client=client)
    outcome = sink.load(rows, source_key=source_key, snapshot_date=snapshot_date)
    build.metadata["bigquery"] = str(outcome)
    log.info("[%s] bigquery: %s", source_key, outcome)
    return outcome
