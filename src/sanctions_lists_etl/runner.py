"""Registry of sanctions sources and the end-to-end driver.

Adding a list means: create ``sources/<name>/`` exporting a ``SOURCE``
(:class:`~.base.Source`), then register it in ``_SOURCES`` below.  Everything
else — the CLI subcommand, ``run_all`` — picks it up automatically.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterable

log = logging.getLogger(__name__)

from .base import Source, SourceResult
from .sources.eu import SOURCE as EU_SOURCE
from .sources.interpol import SOURCE as INTERPOL_SOURCE
from .sources.ofac import SOURCE as OFAC_SOURCE
from .sources.un import SOURCE as UN_SOURCE

_SOURCES: dict[str, Source] = {
    OFAC_SOURCE.name: OFAC_SOURCE,
    EU_SOURCE.name: EU_SOURCE,
    UN_SOURCE.name: UN_SOURCE,
    INTERPOL_SOURCE.name: INTERPOL_SOURCE,
}

DEFAULT_OUTPUT_DIR = Path("data/output")
DEFAULT_RAW_DIR = Path("data/raw")


def available_sources() -> dict[str, Source]:
    return dict(_SOURCES)


def get_source(name: str) -> Source:
    try:
        return _SOURCES[name]
    except KeyError:
        raise KeyError(
            f"unknown source {name!r}; available: {', '.join(sorted(_SOURCES))}"
        ) from None


def run_source(
    name: str,
    *,
    output_dir: Path | str = DEFAULT_OUTPUT_DIR,
    raw_dir: Path | str = DEFAULT_RAW_DIR,
    **options: Any,
) -> SourceResult:
    return get_source(name).run(output_dir=output_dir, raw_dir=raw_dir, **options)


def run_sources(
    names: Iterable[str],
    *,
    output_dir: Path | str = DEFAULT_OUTPUT_DIR,
    raw_dir: Path | str = DEFAULT_RAW_DIR,
    keep_going: bool = False,
) -> list[SourceResult]:
    """Run each named source in turn.

    With ``keep_going`` a source that raises is logged and skipped rather than
    aborting the batch; the collected failures are re-raised as one
    :class:`RuntimeError` once every source has had its turn, so a run that is
    missing a list still exits non-zero.
    """
    results: list[SourceResult] = []
    failures: list[str] = []
    for name in names:
        try:
            results.append(run_source(name, output_dir=output_dir, raw_dir=raw_dir))
        except Exception as exc:  # noqa: BLE001 - surfaced below
            if not keep_going:
                raise
            log.error("[%s] failed: %s", name, exc)
            failures.append(f"{name}: {exc}")
    if failures:
        raise RuntimeError(
            "one or more sources failed:\n  " + "\n  ".join(failures)
        )
    return results


def run_all(
    *,
    output_dir: Path | str = DEFAULT_OUTPUT_DIR,
    raw_dir: Path | str = DEFAULT_RAW_DIR,
    keep_going: bool = True,
) -> list[SourceResult]:
    """Run every registered source with its defaults.

    One source failing (e.g. the EU list without ``EU_FSF_TOKEN`` set) does not
    stop the others; the run still ends with an error listing what failed.
    """
    return run_sources(
        _SOURCES, output_dir=output_dir, raw_dir=raw_dir, keep_going=keep_going
    )
