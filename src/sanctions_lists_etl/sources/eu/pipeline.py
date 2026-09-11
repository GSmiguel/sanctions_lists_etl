"""EU FSF source: consolidated sanctions XML -> flat Excel workbook."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

from ...base import Source, SourceResult
from ...common.pipeline import SourceSpec, build_rows, resolve_input, write_excel
from ...common.sinks.bigquery import load_bigquery
from ...common.sortkeys import reference_sort_key
from .columns import COLUMN_WIDTHS, HEADERS
from .download import download_eu_fsf, redact
from .normalize import to_normalized
from .parser import parse_eu_fsf, rows_from_records

NAME = "eu"
DESCRIPTION = "EU consolidated financial sanctions list (FSF full XML)"
BQ_SOURCE_KEY = "eu_fsf"
PERSONS_ONLY = ("person",)
ENTITIES_ONLY = ("enterprise",)

SPEC = SourceSpec(
    name=NAME,
    description=DESCRIPTION,
    raw_filename="eu_fsf_full.xml",
    output_filename="eu_fsf.xlsx",
    sheet_name="EU",
    headers=HEADERS,
    column_widths=COLUMN_WIDTHS,
    parse=parse_eu_fsf,
    rows_from_records=rows_from_records,
    sort_key=lambda record: reference_sort_key(record.eu_reference_number),
    redact_url=redact,
)


def run(
    *,
    output_dir: Path | str = "data/output",
    raw_dir: Path | str = "data/raw",
    xml_path: Path | str | None = None,
    subject_types: tuple[str, ...] | None = None,
    download: bool = True,
    token: str | None = None,
    url: str | None = None,
    bigquery: bool = False,
    bq_project: str | None = None,
    bq_dataset: str | None = None,
) -> SourceResult:
    """Run the EU pipeline end to end.

    If ``xml_path`` is given it is parsed as-is; otherwise a fresh copy is
    downloaded into ``raw_dir`` (unless ``download`` is ``False`` and a cached
    file already exists).  ``token`` / ``url`` are only consulted when a download
    actually happens — see :mod:`.download` for how the token is resolved.
    ``bigquery`` also loads the parsed rows into BigQuery.
    """
    log.info("[eu] starting")
    source_path, provenance = resolve_input(
        SPEC,
        raw_dir=raw_dir,
        fetch=lambda: download_eu_fsf(raw_dir, token=token, url=url),
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
    if bigquery:
        load_bigquery(
            build, to_normalized, source_key=BQ_SOURCE_KEY, project=bq_project, dataset=bq_dataset
        )
    log.info("[eu] done -> %s", dest)
    return build.to_source_result([dest])


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
    group.add_argument("--persons-only", action="store_true", help="Keep only natural persons.")
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
