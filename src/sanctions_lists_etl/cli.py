"""``sanctions-etl`` command line.

sanctions-etl                   run every source
sanctions-etl all               same, explicit
sanctions-etl all --exclude eu  run every source but one
sanctions-etl ofac [opts]       run one source with its own flags
sanctions-etl --list            show registered sources
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Any

from .base import SourceResult
from .common.schema import DATASET_NAME
from .runner import available_sources, get_source, run_all

BQ_PROJECT_ENV = "BQ_PROJECT"
BQ_DATASET_ENV = "BQ_DATASET"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sanctions-etl",
        description="Download public sanctions lists and load them into BigQuery.",
    )
    parser.add_argument("--list", action="store_true", help="list registered sources and exit")
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="SOURCE",
        choices=sorted(available_sources()),
        help="skip this source when running all (repeatable)",
    )
    parser.add_argument(
        "--bigquery",
        action="store_true",
        help=(
            "also load parsed rows into BigQuery (needs the 'bigquery' extra and "
            f"{BQ_PROJECT_ENV} set; {BQ_DATASET_ENV} defaults to {DATASET_NAME!r})"
        ),
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="only log warnings and errors")
    parser.add_argument("-v", "--verbose", action="store_true", help="log debug-level detail")

    subparsers = parser.add_subparsers(dest="source", metavar="SOURCE")
    subparsers.add_parser("all", help="run every registered source (default)")
    for name, source in sorted(available_sources().items()):
        source_parser = subparsers.add_parser(name, help=source.description)
        source.configure_parser(source_parser)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    level = logging.WARNING if args.quiet else logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.list:
        for name, source in sorted(available_sources().items()):
            print(f"{name:<8} {source.description}")
        return 0

    try:
        bq_options = _bigquery_options(args)
        if args.source in (None, "all"):
            results = run_all(exclude=args.exclude, **bq_options)
        else:
            if args.exclude:
                parser.error("--exclude only applies when running every source")
            source = get_source(args.source)
            options = source.options_from_args(args)
            results = [source.run(**options, **bq_options)]
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    for result in results:
        _print_result(result)
    return 0


def _bigquery_options(args: argparse.Namespace) -> dict[str, Any]:
    if not args.bigquery:
        return {"bigquery": False}
    project = os.environ.get(BQ_PROJECT_ENV)
    if not project:
        raise RuntimeError(f"--bigquery requires {BQ_PROJECT_ENV} to be set")
    return {
        "bigquery": True,
        "bq_project": project,
        "bq_dataset": os.environ.get(BQ_DATASET_ENV, DATASET_NAME),
    }


def _print_result(result: SourceResult) -> None:
    print(f"[{result.source}] {result.record_count} records")
    for party_type, count in sorted(result.counts_by_type.items()):
        print(f"    {party_type:<12} {count}")
    # "bigquery" for single-list sources, "{list}_bigquery" for ofac's two.
    for key, value in sorted(result.metadata.items()):
        if key == "bigquery" or key.endswith("_bigquery"):
            print(f"    {key}: {value}")


if __name__ == "__main__":
    sys.exit(main())
