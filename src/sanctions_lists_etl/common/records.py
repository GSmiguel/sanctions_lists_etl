"""Flatten a source's record dataclass into an ordered ``dict[str, str]`` row.

Every source's ``parser`` module defines its own record dataclass whose
``to_row`` did the same thing: walk ``(attribute, header)`` pairs, join a
list-valued attribute with ``"; "`` after dropping blanks and duplicates, and
pass a scalar through.  That body lives here now; each ``to_row`` is a one-line
call to :func:`flatten_row`.
"""

from __future__ import annotations

from collections.abc import Sequence

LIST_SEP = "; "


def flatten_row(record: object, columns: Sequence[tuple[str, str]]) -> dict[str, str]:
    """Return ``{header: value}`` for each ``(attribute, header)`` in ``columns``.

    A list attribute is de-duplicated (order preserved), stripped of falsy items
    and joined with ``"; "``; anything else is coerced to ``str`` with ``None``
    becoming ``""``.
    """
    row: dict[str, str] = {}
    for attr, header in columns:
        value = getattr(record, attr)
        if isinstance(value, list):
            seen: list[str] = []
            for item in value:
                if item and item not in seen:
                    seen.append(item)
            row[header] = LIST_SEP.join(seen)
        else:
            row[header] = value or ""
    return row


def as_array(value: object) -> list[str]:
    """Coerce a record attribute (list or scalar) into a clean ``list[str]``.

    Used by ``to_normalized`` functions to fill BigQuery ``REPEATED`` fields:
    a list is de-duplicated and stripped of falsy items (same rule as
    :func:`flatten_row`, just not joined into one string); a scalar becomes a
    single-item list, or ``[]`` if falsy.
    """
    if isinstance(value, list):
        seen: list[str] = []
        for item in value:
            if item and item not in seen:
                seen.append(str(item))
        return seen
    return [str(value)] if value else []
