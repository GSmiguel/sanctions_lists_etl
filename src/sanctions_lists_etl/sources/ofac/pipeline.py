"""OFAC source: the SDN and Consolidated (Non-SDN) advanced XML -> flat Excel.

OFAC publishes two lists in the same advanced-XML schema:

* **SDN** — Specially Designated Nationals (``sdn_advanced.xml``).
* **Consolidated / Non-SDN** — SSI, Non-SDN CMIC, Non-SDN Menu-Based Sanctions,
  Non-SDN Palestinian Legislative Council and CAPTA lists (``cons_advanced.xml``).

Both are parsed by the same :func:`~.parser.parse_sdn_advanced` and written with
the same column layout; each list gets its own workbook.  ``--list`` selects
which to build (default: both).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

from ...base import Source, SourceResult
from ...common.excel import write_workbook
from .columns import COLUMN_WIDTHS, HEADERS
from .download import (
    CONS_ADVANCED_URL,
    SDN_ADVANCED_URL,
    DownloadResult,
    download_advanced_xml,
)
from .parser import parse_sdn_advanced, rows_from_records

NAME = "ofac"
DESCRIPTION = "OFAC — SDN and Consolidated (Non-SDN) sanctions lists (advanced XML)"
INDIVIDUALS_AND_ENTITIES = ("Individual", "Entity")


@dataclass(frozen=True)
class _ListSpec:
    key: str
    url: str
    raw_filename: str
    output_filename: str
    sheet_name: str
    label: str


_LISTS: dict[str, _ListSpec] = {
    "sdn": _ListSpec(
        "sdn",
        SDN_ADVANCED_URL,
        "sdn_advanced.xml",
        "ofac_sdn.xlsx",
        "SDN",
        "SDN — Specially Designated Nationals",
    ),
    "consolidated": _ListSpec(
        "consolidated",
        CONS_ADVANCED_URL,
        "cons_advanced.xml",
        "ofac_consolidated.xlsx",
        "CONS",
        "Consolidated (Non-SDN) sanctions list",
    ),
}
ALL_LISTS = ("sdn", "consolidated")


def run(
    *,
    output_dir: Path | str = "data/output",
    raw_dir: Path | str = "data/raw",
    xml_path: Path | str | None = None,
    party_types: tuple[str, ...] | None = None,
    download: bool = True,
    lists: tuple[str, ...] = ALL_LISTS,
) -> SourceResult:
    """Run the OFAC pipeline end to end for each requested list.

    ``lists`` picks the sub-lists to build (``"sdn"`` and/or ``"consolidated"``).
    If ``xml_path`` is given it is parsed as the SDN list (a local file cannot
    imply more than one list); otherwise a fresh copy of each list is downloaded
    into ``raw_dir`` unless ``download`` is ``False`` and a cache already exists.
    Each list is written to its own workbook.
    """
    log.info("[ofac] starting")
    selected = ("sdn",) if xml_path is not None else lists
    if not selected:
        raise ValueError("no OFAC list selected")

    output_dir = Path(output_dir)
    raw_dir = Path(raw_dir)
    generated_at = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")

    per_list: list[tuple[_ListSpec, Path, int, dict[str, int]]] = []
    for key in selected:
        spec = _LISTS[key]
        source, sha256 = _resolve_source(spec, raw_dir, xml_path=xml_path, download=download)
        records = parse_sdn_advanced(source, party_types=party_types)
        records.sort(key=lambda record: _sort_key(record.fixed_ref))
        counts = dict(Counter(record.party_type for record in records))

        metadata = {
            "source": f"OFAC {spec.label}",
            "source_file": source.name,
            "source_sha256": sha256 or "",
            "generated_at": generated_at,
            "record_count": str(len(records)),
            "party_type_filter": ", ".join(party_types) if party_types else "(all)",
            **{f"count_{p.lower()}": str(c) for p, c in sorted(counts.items())},
        }
        dest = output_dir / spec.output_filename
        log.info("[ofac] %s: writing %d rows to %s", spec.key, len(records), dest)
        write_workbook(
            HEADERS,
            rows_from_records(records),
            dest,
            sheet_name=spec.sheet_name,
            column_widths=COLUMN_WIDTHS,
            metadata=metadata,
        )
        per_list.append((spec, dest, len(records), counts))
        log.info("[ofac] %s done -> %s", spec.key, dest)

    total = sum(count for _, _, count, _ in per_list)
    merged: Counter[str] = Counter()
    for _, _, _, counts in per_list:
        merged.update(counts)

    summary = {
        "source": DESCRIPTION,
        "generated_at": generated_at,
        "lists_built": ", ".join(spec.key for spec, _, _, _ in per_list),
        "record_count": str(total),
        "party_type_filter": ", ".join(party_types) if party_types else "(all)",
        **{f"{spec.key}_xlsx": str(dest) for spec, dest, _, _ in per_list},
        **{f"{spec.key}_record_count": str(count) for spec, _, count, _ in per_list},
    }

    return SourceResult(
        source=NAME,
        xlsx_path=per_list[0][1],
        record_count=total,
        counts_by_type=dict(merged),
        metadata=summary,
    )


def configure_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--list",
        dest="ofac_list",
        choices=("sdn", "consolidated", "both"),
        default="both",
        help="Which OFAC list to build (default: both). Ignored when --xml is given.",
    )
    parser.add_argument(
        "--xml",
        type=Path,
        default=None,
        help="Parse this local advanced XML (as the SDN list) instead of downloading.",
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


def options_from_args(args: argparse.Namespace) -> dict[str, Any]:
    options: dict[str, Any] = {"download": not getattr(args, "no_download", False)}
    choice = getattr(args, "ofac_list", "both")
    options["lists"] = ALL_LISTS if choice == "both" else (choice,)
    if getattr(args, "xml", None) is not None:
        options["xml_path"] = args.xml
    if getattr(args, "individuals_entities_only", False):
        options["party_types"] = INDIVIDUALS_AND_ENTITIES
    return options


SOURCE = Source(
    name=NAME,
    description=DESCRIPTION,
    run=run,
    configure_parser=configure_parser,
    options_from_args=options_from_args,
)


def _resolve_source(
    spec: _ListSpec,
    raw_dir: Path,
    *,
    xml_path: Path | str | None,
    download: bool,
) -> tuple[Path, str | None]:
    if xml_path is not None:
        source = Path(xml_path)
        log.info("[ofac] %s: using local XML %s", spec.key, source)
        return source, _cached_sha256(source)

    source = raw_dir / spec.raw_filename
    if download or not source.exists():
        result: DownloadResult = download_advanced_xml(
            raw_dir, url=spec.url, filename=spec.raw_filename
        )
        return result.path, result.sha256

    log.info("[ofac] %s: reusing cached XML %s", spec.key, source)
    return source, _cached_sha256(source)


def _cached_sha256(source: Path) -> str | None:
    meta = source.with_name(source.name + ".meta.json")
    if not meta.exists():
        return None
    try:
        return json.loads(meta.read_text())["sha256"]
    except (ValueError, KeyError):
        return None


def _sort_key(fixed_ref: str) -> tuple[int, str]:
    return (int(fixed_ref), "") if fixed_ref.isdigit() else (2**63, fixed_ref)
