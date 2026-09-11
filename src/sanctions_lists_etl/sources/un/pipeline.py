"""UN Security Council Consolidated List source: full XML -> flat Excel workbook."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

from ...base import Source, SourceResult
from ...common.pipeline import SourceSpec, build_rows, resolve_input, write_excel
from ...common.sortkeys import reference_sort_key
from .columns import COLUMN_WIDTHS, HEADERS
from .download import download_un_consolidated
from .parser import parse_un_consolidated, rows_from_records

NAME = "un"
DESCRIPTION = "UN Security Council Consolidated List (full XML)"
INDIVIDUALS_ONLY = ("INDIVIDUAL",)
ENTITIES_ONLY = ("ENTITY",)

SPEC = SourceSpec(
    name=NAME,
    description=DESCRIPTION,
    raw_filename="un_consolidated.xml",
    output_filename="un_consolidated.xlsx",
    sheet_name="UN",
    headers=HEADERS,
    column_widths=COLUMN_WIDTHS,
    parse=parse_un_consolidated,
    rows_from_records=rows_from_records,
    sort_key=lambda record: reference_sort_key(record.un_reference_number),
)


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
    source_path, provenance = resolve_input(
        SPEC,
        raw_dir=raw_dir,
        fetch=lambda: download_un_consolidated(raw_dir, url=url),
        local_path=xml_path,
        download=download,
    )
    build = build_rows(
        SPEC,
        source_path=source_path,
        provenance=provenance,
        parse_kwargs={"subject_types": subject_types},
        extra_metadata={
            "subject_type_filter": ", ".join(subject_types) if subject_types else "(all)"
        },
    )
    dest = write_excel(build, output_dir)
    log.info("[un] done -> %s", dest)
    return build.to_source_result([dest])


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
    group.add_argument("--individuals-only", action="store_true", help="Keep only individuals.")
    group.add_argument("--entities-only", action="store_true", help="Keep only entities.")


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
