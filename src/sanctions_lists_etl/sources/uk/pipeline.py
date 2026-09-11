"""UK Sanctions List (FCDO) source: full XML -> BigQuery."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

from ...base import Source, SourceResult
from ...common.pipeline import SourceSpec, build_rows, resolve_input
from ...common.sinks.bigquery import load_bigquery
from ...common.sortkeys import reference_sort_key
from .download import download_uk_sanctions
from .normalize import to_normalized
from .parser import parse_uk_sanctions, rows_from_records

NAME = "uk"
DESCRIPTION = "UK Sanctions List (FCDO full XML)"
BQ_SOURCE_KEY = "uk_fcdo"
INDIVIDUALS_ONLY = ("INDIVIDUAL",)
ENTITIES_ONLY = ("ENTITY",)
WITHOUT_SHIPS = ("INDIVIDUAL", "ENTITY")

SPEC = SourceSpec(
    name=NAME,
    description=DESCRIPTION,
    raw_filename="uk_sanctions_list.xml",
    parse=parse_uk_sanctions,
    rows_from_records=rows_from_records,
    sort_key=lambda record: reference_sort_key(record.uk_unique_id),
)


def run(
    *,
    xml_path: Path | str | None = None,
    subject_types: tuple[str, ...] | None = None,
    url: str | None = None,
    bigquery: bool = False,
    bq_project: str | None = None,
    bq_dataset: str | None = None,
) -> SourceResult:
    """Run the UK pipeline end to end.

    If ``xml_path`` is given it is parsed as-is; otherwise a fresh copy is
    downloaded.  No credential is required.  ``bigquery`` also loads the parsed
    rows into BigQuery.
    """
    log.info("[uk] starting")
    content, provenance = resolve_input(
        SPEC,
        fetch=lambda: download_uk_sanctions(url=url),
        local_path=xml_path,
    )
    build = build_rows(
        SPEC,
        content=content,
        provenance=provenance,
        parse_kwargs={"subject_types": subject_types},
        extra_metadata={
            "subject_type_filter": ", ".join(subject_types) if subject_types else "(all)"
        },
    )
    if bigquery:
        load_bigquery(
            build, to_normalized, source_key=BQ_SOURCE_KEY, project=bq_project, dataset=bq_dataset
        )
    log.info("[uk] done: %d records", build.record_count)
    return build.to_source_result()


def configure_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--xml",
        type=Path,
        default=None,
        help="Parse this local UK Sanctions List XML instead of downloading a fresh copy.",
    )
    parser.add_argument(
        "--no-ships",
        action="store_true",
        help="Drop ship (vessel) designations, keeping individuals and entities.",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--individuals-only", action="store_true", help="Keep only individuals.")
    group.add_argument("--entities-only", action="store_true", help="Keep only entities.")


def options_from_args(args: argparse.Namespace) -> dict[str, Any]:
    options: dict[str, Any] = {}
    if getattr(args, "xml", None) is not None:
        options["xml_path"] = args.xml
    if getattr(args, "individuals_only", False):
        options["subject_types"] = INDIVIDUALS_ONLY
    elif getattr(args, "entities_only", False):
        options["subject_types"] = ENTITIES_ONLY
    elif getattr(args, "no_ships", False):
        options["subject_types"] = WITHOUT_SHIPS
    return options


SOURCE = Source(
    name=NAME,
    description=DESCRIPTION,
    run=run,
    configure_parser=configure_parser,
    options_from_args=options_from_args,
)
