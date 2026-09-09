"""Namespace-agnostic helpers for walking ``xml.etree`` trees.

Shared across sources: the OFAC, EU and UN sanctions exports are all XML with a
default namespace, so every parser needs the same "find a child by local name"
and "format a Y/M/D node" primitives.
"""

from __future__ import annotations

from xml.etree.ElementTree import Element


def localname(tag: str) -> str:
    """Return an element tag without its ``{namespace}`` prefix."""
    return tag.rsplit("}", 1)[-1]


def first_child(parent: Element, name: str) -> Element | None:
    for child in parent:
        if localname(child.tag) == name:
            return child
    return None


def children(parent: Element, name: str) -> list[Element]:
    return [child for child in parent if localname(child.tag) == name]


def child_text(parent: Element, name: str) -> str:
    child = first_child(parent, name)
    return (child.text or "").strip() if child is not None else ""


def format_ymd(node: Element | None) -> str:
    """Render a node with ``<Year>/<Month>/<Day>`` children as ``YYYY-MM-DD``.

    Missing month/day are dropped rather than zero-filled.
    """
    if node is None:
        return ""
    year = child_text(node, "Year")
    if not year:
        return ""
    out = year
    month = child_text(node, "Month")
    if month:
        out += f"-{int(month):02d}"
        day = child_text(node, "Day")
        if day:
            out += f"-{int(day):02d}"
    return out


def format_date_period(period: Element) -> str:
    """Render a ``<DatePeriod>`` as a single date or ``start to end`` range."""
    start = first_child(period, "Start")
    end = first_child(period, "End")
    first = format_ymd(first_child(start, "From")) if start is not None else ""
    last = format_ymd(first_child(end, "To")) if end is not None else ""
    if first and last and first != last:
        return f"{first} to {last}"
    return first or last
