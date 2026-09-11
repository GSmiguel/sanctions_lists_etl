"""INTERPOL source: UN Special Notice list -> flat Excel workbook."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

from ...base import Source, SourceResult
from ...common.meta import read_meta
from ...common.pipeline import Provenance, SourceSpec, build_rows, write_excel
from .columns import COLUMN_WIDTHS, HEADERS
from .download import download_interpol
from .parser import Notice, parse_interpol, rows_from_records

NAME = "interpol"
DESCRIPTION = "INTERPOL UN Special Notices (public web service)"


def _sort_key(record: Notice) -> tuple[str, str]:
    """Order rows by UN reference (falling back to name), then id."""
    return (record.un_reference or record.primary_name).upper(), record.interpol_notice_id


SPEC = SourceSpec(
    name=NAME,
    description=DESCRIPTION,
    raw_filename="interpol.json",
    output_filename="interpol.xlsx",
    sheet_name="INTERPOL",
    headers=HEADERS,
    column_widths=COLUMN_WIDTHS,
    parse=parse_interpol,
    rows_from_records=rows_from_records,
    sort_key=_sort_key,
    input_kind="snapshot",
)


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
    if json_path is not None:
        source_path = Path(json_path)
        log.info("[interpol] using local snapshot %s", source_path)
        provenance, coverage = _from_meta(source_path)
    else:
        cached = Path(raw_dir) / SPEC.raw_filename
        if download or not cached.exists():
            result = download_interpol(raw_dir, url=url, limit=limit)
            source_path = result.path
            provenance = Provenance(result.path.name, result.sha256, result.url)
            coverage = result.coverage
        else:
            log.info("[interpol] reusing cached snapshot %s", cached)
            source_path = cached
            provenance, coverage = _from_meta(cached)

    build = build_rows(
        SPEC,
        source_path=source_path,
        provenance=provenance,
        extra_metadata={"coverage": coverage},
    )
    dest = write_excel(build, output_dir)
    log.info("[interpol] done -> %s", dest)
    return build.to_source_result([dest])


def _from_meta(path: Path) -> tuple[Provenance, str]:
    meta = read_meta(path)
    provenance = Provenance(
        source_file=path.name,
        source_sha256=str(meta.get("sha256") or ""),
        source_url=str(meta.get("url") or ""),
    )
    return provenance, str(meta.get("coverage") or "")


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
