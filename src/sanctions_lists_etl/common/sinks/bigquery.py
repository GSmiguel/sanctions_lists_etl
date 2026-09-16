"""BigQuery sink: per-source MERGE (upsert + delete-if-absent) into ``entries``.

``entries`` holds only current state — one row per ``uid`` — kept that way by
loading each source's freshly-normalized rows into a truncate-and-reload
staging table, then MERGE-ing staging into ``entries`` scoped to that source's
`source` value: matched rows are updated, new rows are inserted (stamping
``first_seen_date``/``last_seen_date``), and any row still tagged with this
source but absent from the new load is deleted. Scoping the delete branch to
``source = @source_key`` is what makes a rerun for one source safe without
touching any other source's rows — the same guarantee the old delete-then-
append-per-day design existed for, without ever growing ``entries`` itself.

``google-cloud-bigquery`` is only imported lazily (inside functions), so this
module — and everything that merely calls :func:`load_bigquery` with
``bigquery=False`` — stays importable without the optional ``bigquery``
extra.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from ..pipeline import BuildResult
from ..schema import DATASET_NAME, ENTRIES_FIELDS, ENTRIES_TABLE, MANIFEST_TABLE, STAGING_TABLE

log = logging.getLogger(__name__)

ToNormalized = Callable[..., dict]

_ROW_COLUMNS: list[str] = [name for name, _, _ in ENTRIES_FIELDS]


def _bigquery_module() -> Any:
    try:
        from google.cloud import bigquery
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise RuntimeError(
            "--bigquery needs the optional dependency: `uv sync --extra bigquery`"
        ) from exc
    return bigquery


def entries_schema() -> list[Any]:
    """The row shape sources normalize into — also the staging table's schema."""
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
    """Merges already-normalized rows into ``{project}.{dataset}.entries``."""

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

    def load(self, rows: Sequence[dict], *, source_key: str, load_date: str) -> LoadOutcome:
        if not rows:
            log.info("[bigquery] %s: no rows for %s, nothing to load", source_key, load_date)
            return LoadOutcome(source_key, "skipped (no rows)")

        self._load_staging(rows)
        self._merge_staging_into_entries(source_key=source_key, load_date=load_date)
        log.info("[bigquery] %s: merged %d rows (as of %s)", source_key, len(rows), load_date)
        self._update_manifest(source_key, load_date)
        return LoadOutcome(source_key, "loaded", len(rows))

    def _load_staging(self, rows: Sequence[dict]) -> None:
        bigquery = _bigquery_module()
        job_config = bigquery.LoadJobConfig(
            schema=entries_schema(),
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        )
        job = self.client.load_table_from_json(
            list(rows), self._table_id(STAGING_TABLE), job_config=job_config
        )
        job.result()

    def _merge_staging_into_entries(self, *, source_key: str, load_date: str) -> None:
        bigquery = _bigquery_module()
        update_cols = [c for c in _ROW_COLUMNS if c != "uid"]
        update_set = ", ".join(f"{c} = S.{c}" for c in update_cols)
        insert_cols = [*_ROW_COLUMNS, "first_seen_date", "last_seen_date"]
        insert_vals = [f"S.{c}" for c in _ROW_COLUMNS] + ["@load_date", "@load_date"]
        sql = f"""
        MERGE `{self._table_id(ENTRIES_TABLE)}` T
        USING `{self._table_id(STAGING_TABLE)}` S
        ON T.uid = S.uid
        WHEN MATCHED THEN UPDATE SET {update_set}, last_seen_date = @load_date
        WHEN NOT MATCHED BY TARGET THEN
          INSERT ({", ".join(insert_cols)})
          VALUES ({", ".join(insert_vals)})
        WHEN NOT MATCHED BY SOURCE AND T.source = @source_key THEN DELETE
        """
        self.client.query(
            sql,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("load_date", "DATE", load_date),
                    bigquery.ScalarQueryParameter("source_key", "STRING", source_key),
                ]
            ),
        ).result()

    def _update_manifest(self, source_key: str, load_date: str) -> None:
        bigquery = _bigquery_module()
        sql = f"""
        MERGE `{self._table_id(MANIFEST_TABLE)}` AS target
        USING (SELECT @source AS source, @latest_snapshot_date AS latest_snapshot_date) AS src
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
                    bigquery.ScalarQueryParameter("latest_snapshot_date", "DATE", load_date),
                ]
            ),
        ).result()


def normalized_rows(
    build: BuildResult,
    to_normalized: ToNormalized,
    *,
    source_key: str,
    ingested_at: str,
) -> list[dict]:
    return [
        to_normalized(
            record,
            source_key=source_key,
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
    ``SourceResult.metadata``. Safe to call on every run: ``BigQuerySink.load``
    MERGEs staging into ``entries`` scoped to ``source_key``, so a rerun for
    the same source is idempotent and never touches another source's rows.
    """
    load_date = dt.datetime.now(dt.UTC).date().isoformat()
    ingested_at = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    rows = normalized_rows(build, to_normalized, source_key=source_key, ingested_at=ingested_at)
    sink = BigQuerySink(project=project, dataset=dataset, client=client)
    outcome = sink.load(rows, source_key=source_key, load_date=load_date)
    build.metadata["bigquery"] = str(outcome)
    log.info("[%s] bigquery: %s", source_key, outcome)
    return outcome
