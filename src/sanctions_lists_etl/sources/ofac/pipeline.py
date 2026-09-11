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
import logging
from collections import Counter
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

from ...base import Source, SourceResult
from ...common.pipeline import SourceSpec, build_rows, resolve_input, write_excel
from ...common.sinks.bigquery import load_bigquery
from ...common.sortkeys import reference_sort_key
from .columns import COLUMN_WIDTHS, HEADERS
from .download import CONS_ADVANCED_URL, SDN_ADVANCED_URL, download_advanced_xml
from .normalize import to_normalized
from .parser import parse_sdn_advanced, rows_from_records

NAME = "ofac"
DESCRIPTION = "OFAC — SDN and Consolidated (Non-SDN) sanctions lists (advanced XML)"
INDIVIDUALS_AND_ENTITIES = ("Individual", "Entity")

ALL_LISTS = ("sdn", "consolidated")

_URLS = {"sdn": SDN_ADVANCED_URL, "consolidated": CONS_ADVANCED_URL}
# common.schema.SOURCE_KEYS — the BigQuery `source` value for each sub-list.
_BQ_SOURCE_KEYS = {"sdn": "ofac_sdn", "consolidated": "ofac_consolidated"}


def _spec(description: str, raw_filename: str, output_filename: str, sheet: str) -> SourceSpec:
    return SourceSpec(
        name=NAME,
        description=description,
        raw_filename=raw_filename,
        output_filename=output_filename,
        sheet_name=sheet,
        headers=HEADERS,
        column_widths=COLUMN_WIDTHS,
        parse=parse_sdn_advanced,
        rows_from_records=rows_from_records,
        sort_key=lambda record: reference_sort_key(record.fixed_ref),
    )


_LIST_SPECS: dict[str, SourceSpec] = {
    "sdn": _spec(
        "OFAC SDN — Specially Designated Nationals",
        "sdn_advanced.xml",
        "ofac_sdn.xlsx",
        "SDN",
    ),
    "consolidated": _spec(
        "OFAC Consolidated (Non-SDN) sanctions list",
        "cons_advanced.xml",
        "ofac_consolidated.xlsx",
        "CONS",
    ),
}


def run(
    *,
    output_dir: Path | str = "data/output",
    raw_dir: Path | str = "data/raw",
    xml_path: Path | str | None = None,
    party_types: tuple[str, ...] | None = None,
    download: bool = True,
    lists: tuple[str, ...] = ALL_LISTS,
    bigquery: bool = False,
    bq_project: str | None = None,
    bq_dataset: str | None = None,
) -> SourceResult:
    """Run the OFAC pipeline end to end for each requested list.

    ``lists`` picks the sub-lists to build (``"sdn"`` and/or ``"consolidated"``).
    If ``xml_path`` is given it is parsed as the SDN list (a local file cannot
    imply more than one list); otherwise a fresh copy of each list is downloaded
    into ``raw_dir`` unless ``download`` is ``False`` and a cache already exists.
    Each list is written to its own workbook.  ``bigquery`` also loads each
    list's rows into BigQuery, keyed by its own `source` (``ofac_sdn`` /
    ``ofac_consolidated``).
    """
    log.info("[ofac] starting")
    selected = ("sdn",) if xml_path is not None else lists
    if not selected:
        raise ValueError("no OFAC list selected")

    filter_label = ", ".join(party_types) if party_types else "(all)"
    builds: list[tuple[str, Path, int, str]] = []
    merged: Counter[str] = Counter()

    for key in selected:
        spec = _LIST_SPECS[key]
        source_path, provenance = resolve_input(
            spec,
            raw_dir=raw_dir,
            fetch=lambda k=key: download_advanced_xml(
                raw_dir, url=_URLS[k], filename=_LIST_SPECS[k].raw_filename
            ),
            local_path=xml_path,
            download=download,
        )
        build = build_rows(
            spec,
            source_path=source_path,
            provenance=provenance,
            parse_kwargs={"party_types": party_types},
            extra_metadata={"party_type_filter": filter_label},
        )
        dest = write_excel(build, output_dir)
        if bigquery:
            load_bigquery(
                build,
                to_normalized,
                source_key=_BQ_SOURCE_KEYS[key],
                project=bq_project,
                dataset=bq_dataset,
            )
        log.info("[ofac] %s done -> %s", key, dest)
        builds.append((key, dest, build.record_count, build.metadata.get("bigquery", "")))
        merged.update(build.counts_by_type)

    total = sum(count for _, _, count, _ in builds)
    summary = {
        "source": DESCRIPTION,
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "lists_built": ", ".join(key for key, _, _, _ in builds),
        "record_count": str(total),
        "party_type_filter": filter_label,
        **{f"{key}_xlsx": str(dest) for key, dest, _, _ in builds},
        **{f"{key}_record_count": str(count) for key, _, count, _ in builds},
        **({f"{key}_bigquery": outcome for key, _, _, outcome in builds} if bigquery else {}),
    }
    return SourceResult(
        source=NAME,
        xlsx_path=builds[0][1],
        record_count=total,
        counts_by_type=dict(merged),
        metadata=summary,
        outputs=[dest for _, dest, _, _ in builds],
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
