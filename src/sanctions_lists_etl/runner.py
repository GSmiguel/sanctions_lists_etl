"""Registry of sanctions sources and the end-to-end driver.

Adding a list means: create ``sources/<name>/`` exporting a ``SOURCE``
(:class:`~.base.Source`), then register it in ``_SOURCES`` below.  Everything
else — the CLI subcommand, ``run_all`` — picks it up automatically.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from .base import Source, SourceResult
from .sources.ofac import SOURCE as OFAC_SOURCE

_SOURCES: dict[str, Source] = {
    OFAC_SOURCE.name: OFAC_SOURCE,
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
) -> list[SourceResult]:
    return [
        run_source(name, output_dir=output_dir, raw_dir=raw_dir) for name in names
    ]


def run_all(
    *,
    output_dir: Path | str = DEFAULT_OUTPUT_DIR,
    raw_dir: Path | str = DEFAULT_RAW_DIR,
) -> list[SourceResult]:
    """Run every registered source with its defaults."""
    return run_sources(_SOURCES, output_dir=output_dir, raw_dir=raw_dir)
