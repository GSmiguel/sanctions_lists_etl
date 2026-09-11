"""Order rows by a designation reference number.

Sanctions references mix a letter prefix (a committee or regime code) with one or
more numbers: ``QDi.9`` must sort before ``QDi.100``, ``EU.27.28`` before
``EU.100.1``, ``RUS9`` before ``RUS100``, and a bare ``12345`` numerically.  Every
XML source wanted the same key; this is it.
"""

from __future__ import annotations

import re

_DIGITS = re.compile(r"\d+")
_NON_NUMERIC = re.compile(r"[\d.]")


def reference_sort_key(ref: str) -> tuple[str, tuple[int, ...], str]:
    """Return ``(letter prefix, numeric parts, raw ref)`` for sorting ``ref``.

    ``"QDi.335"`` -> ``("QDi", (335,), "QDi.335")``;
    ``"12345"`` -> ``("", (12345,), "12345")``;
    ``"EU.27.28"`` -> ``("EU", (27, 28), "EU.27.28")``.
    """
    prefix = _NON_NUMERIC.sub("", ref)
    numbers = tuple(int(n) for n in _DIGITS.findall(ref))
    return prefix, numbers, ref
