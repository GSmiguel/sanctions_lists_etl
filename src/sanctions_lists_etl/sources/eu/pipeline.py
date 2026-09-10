"""EU FSF source: consolidated sanctions XML -> flat Excel workbook."""

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
from .download import DownloadResult, download_eu_fsf, redact
from .parser import SanctionEntity, parse_eu_fsf, rows_from_records

NAME = "eu"
DESCRIPTION = "EU consolidated financial sanctions list (FSF full XML)"
OUTPUT_FILENAME = "eu_fsf.xlsx"
RAW_FILENAME = "eu_fsf_full.xml"
PERSONS_ONLY = ("person",)
ENTITIES_ONLY = ("enterprise",)


def run(
    *,
    output_dir: Path | str = "data/output",
    raw_dir: Path | str = "data/raw",
    xml_path: Path | str | None = None,
    subject_types: tuple[str, ...] | None = None,
    download: bool = True,
    token: str | None = None,
    url: str | None = None,
) -> SourceResult:
    """Run the EU pipeline end to end.

    If ``xml_path`` is given it is parsed as-is; otherwise a fresh copy is
    downloaded into ``raw_dir`` (unless ``download`` is ``False`` and a cached
    file already exists).  ``token`` / ``url`` are only consulted when a download
    actually happens — see :mod:`.download` for how the token is resolved.
    """
    log.info("[eu] starting")
    downloaded: DownloadResult | None = None
    if xml_path is not None:
        source = Path(xml_path)
        log.info("[eu] using local XML %s", source)
    else:
        source = Path(raw_dir) / RAW_FILENAME
        if download or not source.exists():
            downloaded = download_eu_fsf(raw_dir, token=token, url=url)
            source = downloaded.path
        else:
            log.info("[eu] reusing cached XML %s", source)

    sha256 = downloaded.sha256 if downloaded else _cached_sha256(source)
    source_url = downloaded.url if downloaded else _cached_url(source)

    records = parse_eu_fsf(source, subject_types=subject_types)
    records.sort(key=_sort_key)
    counts = dict(Counter(record.party_type for record in records))

    metadata = {
        "source": DESCRIPTION,
        "source_file": source.name,
        "source_url": redact(source_url) if source_url else "",
        "source_sha256": sha256 or "",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "record_count": str(len(records)),
        "subject_type_filter": ", ".join(subject_types) if subject_types else "(all)",
        **{f"count_{ptype.lower()}": str(count) for ptype, count in sorted(counts.items())},
    }

    dest = Path(output_dir) / OUTPUT_FILENAME
    log.info("[eu] writing %d rows to %s", len(records), dest)
    xlsx = write_workbook(
        HEADERS,
        rows_from_records(records),
        dest,
        sheet_name="EU",
        column_widths=COLUMN_WIDTHS,
        metadata=metadata,
    )
    log.info("[eu] done -> %s", xlsx)

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
        help="Parse this local EU FSF XML instead of downloading a fresh copy.",
    )
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="Reuse the cached XML in --raw-dir if present.",
    )
    parser.add_argument(
        "--token-file",
        type=Path,
        default=None,
        help=(
            "File whose contents are the FSD web-gate access token. Alternatively "
            "set EU_FSF_TOKEN (or EU_FSF_TOKEN_FILE). The token is a secret."
        ),
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--persons-only", action="store_true", help="Keep only natural persons."
    )
    group.add_argument(
        "--entities-only", action="store_true", help="Keep only enterprises/entities."
    )


def options_from_args(args: argparse.Namespace) -> dict[str, Any]:
    options: dict[str, Any] = {"download": not getattr(args, "no_download", False)}
    if getattr(args, "xml", None) is not None:
        options["xml_path"] = args.xml
    if getattr(args, "persons_only", False):
        options["subject_types"] = PERSONS_ONLY
    elif getattr(args, "entities_only", False):
        options["subject_types"] = ENTITIES_ONLY
    token_file = getattr(args, "token_file", None)
    if token_file is not None:
        path = Path(token_file).expanduser()
        try:
            options["token"] = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise RuntimeError(f"--token-file {path}: {exc.strerror or exc}") from None
    return options


SOURCE = Source(
    name=NAME,
    description=DESCRIPTION,
    run=run,
    configure_parser=configure_parser,
    options_from_args=options_from_args,
)


def _cached_sha256(source: Path) -> str | None:
    return _cached_meta(source, "sha256")


def _cached_url(source: Path) -> str | None:
    return _cached_meta(source, "url")


def _cached_meta(source: Path, key: str) -> str | None:
    meta = source.with_name(source.name + ".meta.json")
    if not meta.exists():
        return None
    try:
        return json.loads(meta.read_text())[key]
    except (ValueError, KeyError):
        return None


def _sort_key(record: SanctionEntity) -> tuple[int, str]:
    lid = record.logical_id
    return (int(lid), "") if lid.isdigit() else (2**63, record.eu_reference_number)
