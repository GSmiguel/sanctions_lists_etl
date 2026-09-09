"""Stage 1 pipeline: OFAC SDN advanced XML -> flat Excel workbook."""

from __future__ import annotations

import datetime as dt
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .download import DownloadResult, download_sdn_advanced
from .excel import write_workbook
from .parser import parse_sdn_advanced, rows_from_records

INDIVIDUALS_AND_ENTITIES = ("Individual", "Entity")


@dataclass(frozen=True)
class PipelineResult:
    xml_path: Path
    xlsx_path: Path
    record_count: int
    counts_by_type: dict[str, int]
    source_sha256: str | None


def run(
    *,
    xml_path: Path | str | None = None,
    xlsx_path: Path | str = "data/output/ofac_sdn.xlsx",
    raw_dir: Path | str = "data/raw",
    party_types: tuple[str, ...] | None = None,
    download: bool = True,
) -> PipelineResult:
    """Run the full stage-1 pipeline.

    If ``xml_path`` is given it is parsed as-is; otherwise a fresh copy is
    downloaded into ``raw_dir`` (unless ``download`` is ``False`` and a cached
    file already exists).
    """
    result: DownloadResult | None = None
    if xml_path is not None:
        source = Path(xml_path)
    else:
        source = Path(raw_dir) / "sdn_advanced.xml"
        if download or not source.exists():
            result = download_sdn_advanced(raw_dir)
            source = result.path

    sha256 = result.sha256 if result else _cached_sha256(source)

    records = parse_sdn_advanced(source, party_types=party_types)
    records.sort(key=lambda record: _sort_key(record.fixed_ref))
    counts = Counter(record.party_type for record in records)

    metadata = {
        "source": "OFAC SDN advanced XML",
        "source_file": source.name,
        "source_sha256": sha256 or "",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "record_count": str(len(records)),
        "party_type_filter": ", ".join(party_types) if party_types else "(all)",
        **{f"count_{ptype.lower()}": str(count) for ptype, count in sorted(counts.items())},
    }

    xlsx = write_workbook(rows_from_records(records), xlsx_path, metadata=metadata)

    return PipelineResult(
        xml_path=source,
        xlsx_path=xlsx,
        record_count=len(records),
        counts_by_type=dict(counts),
        source_sha256=sha256,
    )


def _cached_sha256(source: Path) -> str | None:
    meta = source.with_name(source.name + ".meta.json")
    if meta.exists():
        try:
            return json.loads(meta.read_text())["sha256"]
        except (ValueError, KeyError):
            return None
    return None


def _sort_key(fixed_ref: str) -> tuple[int, str]:
    return (int(fixed_ref), "") if fixed_ref.isdigit() else (2**63, fixed_ref)
