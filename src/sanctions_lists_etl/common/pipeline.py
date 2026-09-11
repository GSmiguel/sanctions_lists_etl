"""The shared download -> parse -> flatten skeleton every source's ``run`` used.

Each source repeated the same body: resolve the input (a local file or a fresh
download), parse it, sort, count party types, assemble a provenance-flavoured
metadata dict, flatten to rows.  This module holds the parts that never varied:

* :class:`SourceSpec` — a source's static configuration.
* :func:`build_rows` — everything from bytes to a :class:`BuildResult` that
  carries both the typed records and the flattened rows.

A source's ``run`` becomes: ``resolve_input(...)`` then ``build_rows(SPEC,
...)`` then, optionally, ``load_bigquery(...)``.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..base import SourceResult
from .download import FetchResult

log = logging.getLogger(__name__)

Parser = Callable[..., list]
RowsFromRecords = Callable[[list], list[dict[str, str]]]
SortKey = Callable[[Any], Any]
Fetcher = Callable[[], FetchResult]


@dataclass(frozen=True)
class SourceSpec:
    """A source's static wiring — everything that does not change between runs."""

    name: str
    description: str
    raw_filename: str
    parse: Parser
    rows_from_records: RowsFromRecords
    sort_key: SortKey
    input_kind: str = "XML"
    redact_url: Callable[[str], str] | None = None


@dataclass(frozen=True)
class Provenance:
    source_file: str
    source_sha256: str
    source_url: str


@dataclass(frozen=True)
class BuildResult:
    """Outcome of :func:`build_rows`: parsed records plus their flattened rows."""

    spec: SourceSpec
    records: list
    rows: list[dict[str, str]]
    counts_by_type: dict[str, int]
    metadata: dict[str, str]
    provenance: Provenance

    @property
    def record_count(self) -> int:
        return len(self.records)

    def to_source_result(self) -> SourceResult:
        return SourceResult(
            source=self.spec.name,
            record_count=self.record_count,
            counts_by_type=self.counts_by_type,
            metadata=self.metadata,
        )


def resolve_input(
    spec: SourceSpec,
    *,
    fetch: Fetcher,
    local_path: Path | str | None,
) -> tuple[bytes, Provenance]:
    """Return the bytes to parse and where they came from.

    ``local_path`` wins — its bytes are read straight off disk and hashed for
    provenance; otherwise a fresh download is fetched via ``fetch``.
    """
    if local_path is not None:
        path = Path(local_path)
        log.info("[%s] using local %s %s", spec.name, spec.input_kind, path)
        content = path.read_bytes()
        return content, Provenance(
            source_file=path.name,
            source_sha256=hashlib.sha256(content).hexdigest(),
            source_url="",
        )

    result = fetch()
    url = result.url
    if url and spec.redact_url is not None:
        url = spec.redact_url(url)
    return result.content, Provenance(
        source_file=spec.raw_filename,
        source_sha256=result.sha256,
        source_url=url,
    )


def build_rows(
    spec: SourceSpec,
    *,
    content: bytes,
    provenance: Provenance,
    parse_kwargs: Mapping[str, Any] | None = None,
    extra_metadata: Mapping[str, str] | None = None,
) -> BuildResult:
    """Parse ``content``, sort, count, and flatten — no sink is written."""
    records = spec.parse(content, **(parse_kwargs or {}))
    records.sort(key=spec.sort_key)
    counts = dict(Counter(getattr(r, "party_type", "Unknown") for r in records))

    metadata: dict[str, str] = {
        "source": spec.description,
        "source_file": provenance.source_file,
        "source_url": provenance.source_url,
        "source_sha256": provenance.source_sha256,
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "record_count": str(len(records)),
        **{f"count_{ptype.lower()}": str(count) for ptype, count in sorted(counts.items())},
    }
    if extra_metadata:
        metadata.update(extra_metadata)

    log.info("[%s] parsed %d records", spec.name, len(records))
    return BuildResult(
        spec=spec,
        records=records,
        rows=spec.rows_from_records(records),
        counts_by_type=counts,
        metadata=metadata,
        provenance=provenance,
    )
