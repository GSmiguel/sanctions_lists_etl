"""``sanctions-etl`` command line.

sanctions-etl                 run every source
sanctions-etl all             same, explicit
sanctions-etl ofac [opts]     run one source with its own flags
sanctions-etl --list          show registered sources
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .base import SourceResult
from .runner import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_RAW_DIR,
    available_sources,
    get_source,
    run_all,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sanctions-etl",
        description="Download public sanctions lists and flatten them into Excel workbooks.",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="where .xlsx files are written"
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=DEFAULT_RAW_DIR,
        help="where downloaded source files are cached",
    )
    parser.add_argument("--list", action="store_true", help="list registered sources and exit")
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
        if args.source in (None, "all"):
            results = run_all(output_dir=args.output_dir, raw_dir=args.raw_dir)
        else:
            source = get_source(args.source)
            options = source.options_from_args(args)
            results = [source.run(output_dir=args.output_dir, raw_dir=args.raw_dir, **options)]
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    for result in results:
        _print_result(result)
    return 0


def _print_result(result: SourceResult) -> None:
    print(f"[{result.source}] {result.record_count} records -> {result.xlsx_path}")
    for party_type, count in sorted(result.counts_by_type.items()):
        print(f"    {party_type:<12} {count}")


if __name__ == "__main__":
    sys.exit(main())
