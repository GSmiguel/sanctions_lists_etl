"""INTERPOL source: UN Special Notice list -> flat Excel workbook."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

from ...base import Source, SourceResult
from ...common.excel import write_workbook
from .columns import COLUMN_WIDTHS, HEADERS
from .download import DownloadResult, download_interpol
from .parser import Notice, parse_interpol, rows_from_records

NAME = "interpol"
DESCRIPTION = "INTERPOL UN Special Notices (public web service)"
OUTPUT_FILENAME = "interpol.xlsx"
RAW_FILENAME = "interpol.json"


def run(
    *,
    output_dir: Path | str = "data/output",
    raw_dir: Path | str = "data/raw",
    json_path: Path | str | None = None,
    download: bool = True,
    url: str | None = None,
    limit: int | None = None,
) -> SourceResult:
    """Run the INTERPOL pipeline end to end.

    If ``json_path`` is given it is parsed as-is; otherwise the UN Special Notice
    list is crawled into ``raw_dir`` (unless ``download`` is ``False`` and a
    cached snapshot already exists).  No credential is required.  ``limit`` caps
    the snapshot size (smoke tests).
    """
    log.info("[interpol] starting")
    downloaded: DownloadResult | None = None
    if json_path is not None:
        source = Path(json_path)
        log.info("[interpol] using local snapshot %s", source)
    else:
        source = Path(raw_dir) / RAW_FILENAME
        if download or not source.exists():
            downloaded = download_interpol(raw_dir, url=url, limit=limit)
            source = downloaded.path
        else:
            log.info("[interpol] reusing cached snapshot %s", source)

    sha256 = downloaded.sha256 if downloaded else _cached_meta(source, "sha256")
    source_url = downloaded.url if downloaded else _cached_meta(source, "url")
    coverage = downloaded.coverage if downloaded else _cached_meta(source, "coverage")

    records = parse_interpol(source)
    records.sort(key=_sort_key)
    counts = dict(Counter(record.party_type for record in records))

    metadata = {
        "source": DESCRIPTION,
        "source_file": source.name,
        "source_url": source_url or "",
        "source_sha256": sha256 or "",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "record_count": str(len(records)),
        "coverage": coverage or "",
        **{f"count_{ptype.lower()}": str(count) for ptype, count in sorted(counts.items())},
    }

    dest = Path(output_dir) / OUTPUT_FILENAME
    log.info("[interpol] writing %d rows to %s", len(records), dest)
    xlsx = write_workbook(
        HEADERS,
        rows_from_records(records),
        dest,
        sheet_name="INTERPOL",
        column_widths=COLUMN_WIDTHS,
        metadata=metadata,
    )
    log.info("[interpol] done -> %s", xlsx)

    return SourceResult(
        source=NAME,
        xlsx_path=xlsx,
        record_count=len(records),
        counts_by_type=counts,
        metadata=metadata,
    )


def configure_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        help="Parse this local INTERPOL snapshot instead of crawling the web service.",
    )
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="Reuse the cached snapshot in --raw-dir if present.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Keep only the first N notices in the snapshot (smoke test).",
    )


def options_from_args(args: argparse.Namespace) -> dict[str, Any]:
    options: dict[str, Any] = {"download": not getattr(args, "no_download", False)}
    if getattr(args, "json", None) is not None:
        options["json_path"] = args.json
    if getattr(args, "limit", None) is not None:
        options["limit"] = args.limit
    return options


SOURCE = Source(
    name=NAME,
    description=DESCRIPTION,
    run=run,
    configure_parser=configure_parser,
    options_from_args=options_from_args,
)


def _cached_meta(source: Path, key: str) -> str | None:
    meta = source.with_name(source.name + ".meta.json")
    if not meta.exists():
        return None
    try:
        value = json.loads(meta.read_text())[key]
    except (ValueError, KeyError):
        return None
    return value if isinstance(value, str) else None


def _sort_key(record: Notice) -> tuple[str, str]:
    """Order rows by UN reference (falling back to name), then id."""
    return (record.un_reference or record.primary_name).upper(), record.interpol_notice_id
