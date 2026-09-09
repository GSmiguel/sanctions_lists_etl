"""Command-line entry point for stage 1 of the sanctions ETL."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .pipeline import INDIVIDUALS_AND_ENTITIES, run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sanctions-etl",
        description="Download the OFAC SDN advanced XML and flatten it into an Excel workbook.",
    )
    parser.add_argument(
        "--xml",
        type=Path,
        default=None,
        help="Parse this local sdn_advanced.xml instead of downloading a fresh copy.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("data/output/ofac_sdn.xlsx"),
        help="Destination .xlsx path (default: data/output/ofac_sdn.xlsx).",
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=Path("data/raw"),
        help="Directory for the downloaded XML and its metadata (default: data/raw).",
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    party_types = INDIVIDUALS_AND_ENTITIES if args.individuals_entities_only else None

    result = run(
        xml_path=args.xml,
        xlsx_path=args.out,
        raw_dir=args.raw_dir,
        party_types=party_types,
        download=not args.no_download,
    )

    print(f"Parsed {result.record_count} sanctioned parties from {result.xml_path}")
    for party_type, count in sorted(result.counts_by_type.items()):
        print(f"  {party_type:<12} {count}")
    print(f"Wrote {result.xlsx_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
