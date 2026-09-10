"""UN Security Council Consolidated List source: full XML -> flat Excel workbook."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import re
from collections import Counter
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

from ...base import Source, SourceResult
from ...common.excel import write_workbook
from .columns import COLUMN_WIDTHS, HEADERS
from .download import DownloadResult, download_un_consolidated
from .parser import SanctionParty, parse_un_consolidated, rows_from_records

NAME = "un"
DESCRIPTION = "UN Security Council Consolidated List (full XML)"
OUTPUT_FILENAME = "un_consolidated.xlsx"
RAW_FILENAME = "un_consolidated.xml"
INDIVIDUALS_ONLY = ("INDIVIDUAL",)
ENTITIES_ONLY = ("ENTITY",)


def run(
    *,
    output_dir: Path | str = "data/output",
    raw_dir: Path | str = "data/raw",
    xml_path: Path | str | None = None,
    subject_types: tuple[str, ...] | None = None,
    download: bool = True,
    url: str | None = None,
) -> SourceResult:
    """Run the UN pipeline end to end.

    If ``xml_path`` is given it is parsed as-is; otherwise a fresh copy is
    downloaded into ``raw_dir`` (unless ``download`` is ``False`` and a cached
    file already exists).  No credential is required.
    """
    log.info("[un] starting")
    downloaded: DownloadResult | None = None
    if xml_path is not None:
        source = Path(xml_path)
        log.info("[un] using local XML %s", source)
    else:
        source = Path(raw_dir) / RAW_FILENAME
        if download or not source.exists():
            downloaded = download_un_consolidated(raw_dir, url=url)
            source = downloaded.path
        else:
            log.info("[un] reusing cached XML %s", source)

    sha256 = downloaded.sha256 if downloaded else _cached_meta(source, "sha256")
    source_url = downloaded.url if downloaded else _cached_meta(source, "url")

    records = parse_un_consolidated(source, subject_types=subject_types)
    records.sort(key=_sort_key)
    counts = dict(Counter(record.party_type for record in records))

    metadata = {
        "source": DESCRIPTION,
        "source_file": source.name,
        "source_url": source_url or "",
        "source_sha256": sha256 or "",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "record_count": str(len(records)),
        "subject_type_filter": ", ".join(subject_types) if subject_types else "(all)",
        **{f"count_{ptype.lower()}": str(count) for ptype, count in sorted(counts.items())},
    }

    dest = Path(output_dir) / OUTPUT_FILENAME
    log.info("[un] writing %d rows to %s", len(records), dest)
    xlsx = write_workbook(
        HEADERS,
        rows_from_records(records),
        dest,
        sheet_name="UN",
        column_widths=COLUMN_WIDTHS,
        metadata=metadata,
    )
    log.info("[un] done -> %s", xlsx)

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
        help="Parse this local UN consolidated XML instead of downloading a fresh copy.",
    )
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="Reuse the cached XML in --raw-dir if present.",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--individuals-only", action="store_true", help="Keep only individuals."
    )
    group.add_argument(
        "--entities-only", action="store_true", help="Keep only entities."
    )


def options_from_args(args: argparse.Namespace) -> dict[str, Any]:
    options: dict[str, Any] = {"download": not getattr(args, "no_download", False)}
    if getattr(args, "xml", None) is not None:
        options["xml_path"] = args.xml
    if getattr(args, "individuals_only", False):
        options["subject_types"] = INDIVIDUALS_ONLY
    elif getattr(args, "entities_only", False):
        options["subject_types"] = ENTITIES_ONLY
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
        return json.loads(meta.read_text())[key]
    except (ValueError, KeyError):
        return None


def _sort_key(record: SanctionParty) -> tuple[str, tuple[int, ...], str]:
    """Order rows by reference number: committee prefix, then number (``QDi.9``
    before ``QDi.100``)."""
    ref = record.un_reference_number
    prefix = re.sub(r"[\d.]", "", ref)
    return prefix, tuple(int(n) for n in re.findall(r"\d+", ref)), ref
