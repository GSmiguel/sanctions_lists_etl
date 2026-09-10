"""Read and write the ``<file>.meta.json`` provenance sidecar.

Every source drops a small JSON file next to each download recording its
SHA-256, size, timestamp and (redacted) URL so a later stage can tell which
snapshot it is working from.  These helpers are the one place that shape is
read and written.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def meta_path(target: Path | str) -> Path:
    """Return the ``<target>.meta.json`` sidecar path for ``target``."""
    target = Path(target)
    return target.with_name(target.name + ".meta.json")


def read_meta(target: Path | str) -> dict[str, Any]:
    """Return the sidecar contents for ``target``, or ``{}`` if absent/unreadable."""
    path = meta_path(target)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def read_meta_value(target: Path | str, key: str) -> str | None:
    """Return one string field from ``target``'s sidecar, or ``None``."""
    value = read_meta(target).get(key)
    return value if isinstance(value, str) else None


def write_meta(target: Path | str, data: dict[str, Any]) -> Path:
    """Write ``data`` as ``target``'s sidecar and return the sidecar path."""
    path = meta_path(target)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
