"""OFAC SDN source: advanced XML -> flat Excel workbook."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from collections import Counter
from pathlib import Path
from typing import Any

from ...base import Source, SourceResult
from ...common.excel import write_workbook
from .columns import COLUMN_WIDTHS, HEADERS
from .download import DownloadResult, download_sdn_advanced
from .parser import parse_sdn_advanced, rows_from_records

NAME = "ofac"
DESCRIPTION = "OFAC SDN — Specially Designated Nationals (advanced XML)"
OUTPUT_FILENAME = "ofac_sdn.xlsx"
RAW_FILENAME = "sdn_advanced.xml"
INDIVIDUALS_AND_ENTITIES = ("Individual", "Entity")


def run(
    *,
    output_dir: Path | str = "data/output",
    raw_dir: Path | str = "data/raw",
    xml_path: Path | str | None = None,
    party_types: tuple[str, ...] | None = None,
    download: bool = True,
) -> SourceResult:
    """Run the OFAC pipeline end to end.

    If ``xml_path`` is given it is parsed as-is; otherwise a fresh copy is
    downloaded into ``raw_dir`` (unless ``download`` is ``False`` and a cached
    file already exists).
    """
    downloaded: DownloadResult | None = None
    if xml_path is not None:
        source = Path(xml_path)
    else:
        source = Path(raw_dir) / RAW_FILENAME
        if download or not source.exists():
            downloaded = download_sdn_advanced(raw_dir)
            source = downloaded.path

    sha256 = downloaded.sha256 if downloaded else _cached_sha256(source)

    records = parse_sdn_advanced(source, party_types=party_types)
    records.sort(key=lambda record: _sort_key(record.fixed_ref))
    counts = dict(Counter(record.party_type for record in records))

    metadata = {
        "source": DESCRIPTION,
        "source_file": source.name,
        "source_sha256": sha256 or "",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "record_count": str(len(records)),
        "party_type_filter": ", ".join(party_types) if party_types else "(all)",
        **{f"count_{ptype.lower()}": str(count) for ptype, count in sorted(counts.items())},
    }

    xlsx = write_workbook(
        HEADERS,
        rows_from_records(records),
        Path(output_dir) / OUTPUT_FILENAME,
        sheet_name="SDN",
        column_widths=COLUMN_WIDTHS,
        metadata=metadata,
    )

    return SourceResult(
        source=NAME,
        xlsx_path=xlsx,
        record_count=len(records),
        counts_by_type=counts,
        metadata=metadata,
    )


def configure_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--xml",
        type=Path,
        default=None,
        help="Parse this local sdn_advanced.xml instead of downloading a fresh copy.",
    )
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="Reuse the cached XML in --raw-dir if present.",
    )
    parser.add_argument(
        "--individuals-entities-only",
        action="store_true",
        help="Keep only individuals and entities (drop vessels and aircraft).",
    )


def options_from_args(args: argparse.Namespace) -> dict[str, Any]:
    options: dict[str, Any] = {"download": not getattr(args, "no_download", False)}
    if getattr(args, "xml", None) is not None:
        options["xml_path"] = args.xml
    if getattr(args, "individuals_entities_only", False):
        options["party_types"] = INDIVIDUALS_AND_ENTITIES
    return options


SOURCE = Source(
    name=NAME,
    description=DESCRIPTION,
    run=run,
    configure_parser=configure_parser,
    options_from_args=options_from_args,
)


def _cached_sha256(source: Path) -> str | None:
    meta = source.with_name(source.name + ".meta.json")
    if not meta.exists():
        return None
    try:
        return json.loads(meta.read_text())["sha256"]
    except (ValueError, KeyError):
        return None


def _sort_key(fixed_ref: str) -> tuple[int, str]:
    return (int(fixed_ref), "") if fixed_ref.isdigit() else (2**63, fixed_ref)
