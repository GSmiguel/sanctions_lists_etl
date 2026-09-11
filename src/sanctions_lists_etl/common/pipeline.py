"""The shared download -> parse -> flatten skeleton every source's ``run`` used.

Each source repeated the same body: resolve the input (a local file, a fresh
download, or the cached copy), parse it, sort, count party types, assemble a
provenance-flavoured metadata dict, flatten to rows, write a workbook.  This
module holds the parts that never varied:

* :class:`SourceSpec` — a source's static configuration.
* :func:`build_rows` — everything up to (but not including) writing a sink,
  returning a :class:`BuildResult` that carries both the typed records and the
  flattened rows.
* :func:`write_excel` — the one sink there is today.

A source's ``run`` becomes: ``build_rows(SPEC, ...)`` then ``write_excel(...)``
then ``BuildResult.to_source_result(...)``.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..base import SourceResult
from .download import FetchResult
from .excel import write_workbook
from .meta import read_meta

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
    output_filename: str
    sheet_name: str
    headers: Sequence[str]
    column_widths: Mapping[str, int]
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
    not_modified: bool = False


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

    def to_source_result(self, outputs: Sequence[Path | str]) -> SourceResult:
        paths = [Path(p) for p in outputs]
        return SourceResult(
            source=self.spec.name,
            xlsx_path=paths[0],
            outputs=paths,
            record_count=self.record_count,
            counts_by_type=self.counts_by_type,
            metadata=self.metadata,
        )


def resolve_input(
    spec: SourceSpec,
    *,
    raw_dir: Path | str,
    fetch: Fetcher,
    local_path: Path | str | None,
    download: bool,
) -> tuple[Path, Provenance]:
    """Return the file to parse and where it came from.

    ``local_path`` wins; otherwise a fresh download unless ``download`` is
    ``False`` and ``raw_dir/<raw_filename>`` already exists.
    """
    if local_path is not None:
        path = Path(local_path)
        log.info("[%s] using local %s %s", spec.name, spec.input_kind, path)
        return path, _provenance(spec, path, read_meta(path))

    cached = Path(raw_dir) / spec.raw_filename
    if download or not cached.exists():
        result = fetch()
        return result.path, Provenance(
            source_file=result.path.name,
            source_sha256=result.sha256,
            source_url=result.url,
            not_modified=result.not_modified,
        )

    log.info("[%s] reusing cached %s %s", spec.name, spec.input_kind, cached)
    return cached, _provenance(spec, cached, read_meta(cached))


def _provenance(spec: SourceSpec, path: Path, meta: Mapping[str, Any]) -> Provenance:
    url = meta.get("url") or ""
    if url and spec.redact_url is not None:
        url = spec.redact_url(url)
    return Provenance(
        source_file=path.name,
        source_sha256=str(meta.get("sha256") or ""),
        source_url=str(url),
    )


def build_rows(
    spec: SourceSpec,
    *,
    source_path: Path,
    provenance: Provenance,
    parse_kwargs: Mapping[str, Any] | None = None,
    extra_metadata: Mapping[str, str] | None = None,
) -> BuildResult:
    """Parse ``source_path``, sort, count, and flatten — no sink is written."""
    records = spec.parse(source_path, **(parse_kwargs or {}))
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


def write_excel(build: BuildResult, output_dir: Path | str) -> Path:
    """Write ``build`` to ``output_dir/<output_filename>`` and return the path."""
    dest = Path(output_dir) / build.spec.output_filename
    log.info("[%s] writing %d rows to %s", build.spec.name, build.record_count, dest)
    return write_workbook(
        build.spec.headers,
        build.rows,
        dest,
        sheet_name=build.spec.sheet_name,
        column_widths=build.spec.column_widths,
        metadata=build.metadata,
    )
