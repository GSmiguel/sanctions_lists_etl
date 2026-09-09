"""The contract every sanctions source implements.

A source is a small bundle: a name, a description, a ``run`` callable that does
the whole download -> parse -> Excel job, and two optional hooks that let it add
its own CLI flags.  ``runner`` keeps a registry of these; ``cli`` turns each into
a subcommand.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class SourceResult:
    """Outcome of running one source end to end."""

    source: str
    xlsx_path: Path
    record_count: int
    counts_by_type: dict[str, int] = field(default_factory=dict)
    metadata: dict[str, str] = field(default_factory=dict)


ConfigureParser = Callable[[argparse.ArgumentParser], None]
OptionsFromArgs = Callable[[argparse.Namespace], dict[str, Any]]
RunCallable = Callable[..., SourceResult]


def _noop_configure(parser: argparse.ArgumentParser) -> None:  # pragma: no cover - trivial
    return None


def _no_options(args: argparse.Namespace) -> dict[str, Any]:  # pragma: no cover - trivial
    return {}


@dataclass(frozen=True)
class Source:
    name: str
    description: str
    run: RunCallable
    configure_parser: ConfigureParser = _noop_configure
    options_from_args: OptionsFromArgs = _no_options
