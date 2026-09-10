"""Stream the UN Consolidated List XML into flat :class:`SanctionParty` rows.

The UN export is flat like the EU one — no reference tables.  The document is

    <CONSOLIDATED_LIST>
      <INDIVIDUALS><INDIVIDUAL>...</INDIVIDUAL>...</INDIVIDUALS>
      <ENTITIES><ENTITY>...</ENTITY>...</ENTITIES>
    </CONSOLIDATED_LIST>

and every ``<INDIVIDUAL>`` / ``<ENTITY>`` carries all of its names, aliases,
birth dates, addresses and documents inline as child elements whose values are
element *text* (not attributes, unlike the EU format).  A single ``iterparse``
pass with ``elem.clear()`` after each party is enough; the party type comes
straight from the ``INDIVIDUAL`` / ``ENTITY`` tag, so no forward join is needed.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree.ElementTree import Element, iterparse

log = logging.getLogger(__name__)

from ...common.xmlutils import child_text, children, localname
from .columns import COLUMNS

_LIST_SEP = "; "
_PART_SEP = ", "

# INDIVIDUAL / ENTITY tag -> the vocabulary shared with the OFAC and EU exports.
_TYPE_BY_TAG = {"INDIVIDUAL": "Individual", "ENTITY": "Entity"}

# Special-notice boilerplate the UN mixes into the free-text COMMENTS1 field; it
# carries no information (the notice link is captured structurally in
# interpol_notice), so it is scrubbed from remarks.  Order matters: drop the
# "Photo(graph)... available for inclusion in ... Special Notice" sentence
# wherever it occurs, then the trailing "... Special Notice: <url>" tail.
_PHOTO_BOILERPLATE = re.compile(
    r"\s*(?:Photo(?:graph)?|Picture)s?(?: and fingerprints)?(?: is| are)?"
    r" (?:available for inclusion in|included in)"
    r" (?:the )?INTERPOL-UN(?:SC)?(?: Security Council)? Special Notice\.?",
    re.IGNORECASE,
)
_INTERPOL_TAIL = re.compile(
    r"[\s.]*INTERPOL-UN(?:SC)?(?: Security Council)? Special Notice(\s*:.*)?$",
    re.DOTALL,
)
_ORPHAN_PUNCT = re.compile(r"\s+([.,;])")
_GENDER_IN_COMMENT = re.compile(r"(?:gender|sex)\s*:\s*(male|female)", re.IGNORECASE)


def _clean_comment(text: str) -> str:
    text = " ".join(text.split())
    text = _INTERPOL_TAIL.sub("", _PHOTO_BOILERPLATE.sub("", text))
    text = _ORPHAN_PUNCT.sub(r"\1", text)
    return re.sub(r"\s{2,}", " ", text).strip(" .,;")


@dataclass
class SanctionParty:
    un_reference_number: str
    data_id: str = ""
    party_type: str = "Unknown"
    primary_name: str = ""
    name_original_script: str = ""
    aliases: list[str] = field(default_factory=list)
    birth_dates: list[str] = field(default_factory=list)
    birth_places: list[str] = field(default_factory=list)
    nationalities: list[str] = field(default_factory=list)
    genders: list[str] = field(default_factory=list)
    titles: list[str] = field(default_factory=list)
    designations: list[str] = field(default_factory=list)
    address_countries: list[str] = field(default_factory=list)
    addresses: list[str] = field(default_factory=list)
    documents: list[str] = field(default_factory=list)
    un_list_type: str = ""
    sanctions_lists: list[str] = field(default_factory=list)
    listed_on: list[str] = field(default_factory=list)
    last_updated: list[str] = field(default_factory=list)
    last_reviewed_on: list[str] = field(default_factory=list)
    interpol_notice: str = ""
    comments: str = ""

    def to_row(self) -> dict[str, str]:
        row: dict[str, str] = {}
        for attr, header in COLUMNS:
            value = getattr(self, attr)
            if isinstance(value, list):
                seen: list[str] = []
                for item in value:
                    if item and item not in seen:
                        seen.append(item)
                row[header] = _LIST_SEP.join(seen)
            else:
                row[header] = value or ""
        return row


def parse_un_consolidated(
    source: Path | str,
    *,
    subject_types: Iterable[str] | None = None,
) -> list[SanctionParty]:
    """Parse ``source`` and return one :class:`SanctionParty` per listed party.

    ``subject_types`` optionally restricts the output to ``"INDIVIDUAL"`` and/or
    ``"ENTITY"`` (case-insensitive).
    """
    keep = {t.upper() for t in subject_types} if subject_types is not None else None

    records: list[SanctionParty] = []
    seen = 0

    log.info("parsing %s", source)
    for _, elem in iterparse(str(source), events=("end",)):
        tag = localname(elem.tag)
        if tag not in _TYPE_BY_TAG:
            continue
        seen += 1
        if keep is None or tag in keep:
            records.append(_build_party(elem, tag))
        elem.clear()
        if seen % 2000 == 0:
            log.info("  %d parties parsed (%d kept)", seen, len(records))

    log.info("parsed %d parties (%d kept)", seen, len(records))
    return records


def rows_from_records(records: Iterable[SanctionParty]) -> list[dict[str, str]]:
    return [record.to_row() for record in records]


# --------------------------------------------------------------------------- #
# party assembly
# --------------------------------------------------------------------------- #
def _build_party(party: Element, tag: str) -> SanctionParty:
    record = SanctionParty(
        un_reference_number=child_text(party, "REFERENCE_NUMBER"),
        data_id=child_text(party, "DATAID"),
        party_type=_TYPE_BY_TAG[tag],
        primary_name=_primary_name(party),
        name_original_script=child_text(party, "NAME_ORIGINAL_SCRIPT"),
        un_list_type=child_text(party, "UN_LIST_TYPE"),
    )

    comment = " ".join(child_text(party, "COMMENTS1").split())
    record.comments = _clean_comment(comment)

    for alias in children(party, "INDIVIDUAL_ALIAS") + children(party, "ENTITY_ALIAS"):
        rendered = _format_alias(alias)
        if rendered:
            record.aliases.append(rendered)

    record.birth_dates = [
        rendered
        for node in children(party, "INDIVIDUAL_DATE_OF_BIRTH")
        if (rendered := _format_birthdate(node))
    ]
    record.birth_places = [
        rendered
        for node in children(party, "INDIVIDUAL_PLACE_OF_BIRTH")
        if (
            rendered := _join_location(
                node, ("STREET", "CITY", "STATE_PROVINCE", "COUNTRY", "NOTE")
            )
        )
    ]

    record.nationalities = _values(party, "NATIONALITY")
    record.titles = _values(party, "TITLE")
    record.designations = _values(party, "DESIGNATION")
    record.sanctions_lists = _values(party, "LIST_TYPE")
    record.last_updated = _values(party, "LAST_DAY_UPDATED")
    record.last_reviewed_on = _values(party, "LAST_REVIEWED_ON")

    gender = child_text(party, "GENDER")
    if not gender:
        match = _GENDER_IN_COMMENT.search(comment)
        gender = match.group(1).title() if match else ""
    if gender:
        record.genders.append(gender)

    for address in children(party, "INDIVIDUAL_ADDRESS") + children(party, "ENTITY_ADDRESS"):
        country = child_text(address, "COUNTRY")
        if country:
            record.address_countries.append(country)
        rendered = _join_location(
            address, ("STREET", "CITY", "STATE_PROVINCE", "ZIP_CODE", "COUNTRY", "NOTE")
        )
        if rendered:
            record.addresses.append(rendered)

    record.documents = [
        rendered
        for node in children(party, "INDIVIDUAL_DOCUMENT")
        if (rendered := _format_document(node))
    ]

    listed_on = child_text(party, "LISTED_ON")
    if listed_on:
        record.listed_on.append(listed_on)

    if child_text(party, "HAS_INTERPOL_LINK").upper() == "YES":
        record.interpol_notice = child_text(party, "INTERPOL_LINK")

    return record


def _primary_name(party: Element) -> str:
    """Join the ordered ``FIRST_NAME`` .. ``FOURTH_NAME`` parts into one name.

    Entities carry the whole name in ``FIRST_NAME`` alone; individuals split it
    across up to four numbered parts, published in name order (not surname-first
    like the OFAC export).
    """
    parts: list[str] = []
    for child in party:
        name = localname(child.tag)
        if name.endswith("_NAME") and name != "NAME_ORIGINAL_SCRIPT":
            text = (child.text or "").strip()
            if text:
                parts.append(text)
    return " ".join(" ".join(parts).split())


def _format_alias(alias: Element) -> str:
    name = child_text(alias, "ALIAS_NAME")
    if not name:
        return ""
    quality = child_text(alias, "QUALITY").lower()
    if quality == "low":
        name += " (low quality)"
    elif quality in ("f.k.a.", "fka"):
        name += " (fka)"
    born = _join_location(alias, ("DATE_OF_BIRTH", "CITY_OF_BIRTH", "COUNTRY_OF_BIRTH"))
    if born:
        name += f" (b. {born})"
    note = child_text(alias, "NOTE")
    if note:
        name += f" — {note}"
    return name


def _format_birthdate(node: Element) -> str:
    kind = child_text(node, "TYPE_OF_DATE").upper()
    exact = child_text(node, "DATE")

    if exact:
        rendered = exact
    else:
        from_year = child_text(node, "FROM_YEAR")
        to_year = child_text(node, "TO_YEAR")
        if from_year or to_year:
            rendered = (
                from_year
                if from_year == to_year or not to_year
                else to_year
                if not from_year
                else f"{from_year}-{to_year}"
            )
        else:
            year = child_text(node, "YEAR")
            if not year:
                return ""
            rendered = year
            month = child_text(node, "MONTH")
            if month and month.isdigit():
                rendered += f"-{int(month):02d}"
                day = child_text(node, "DAY")
                if day and day.isdigit():
                    rendered += f"-{int(day):02d}"

    if kind == "APPROXIMATELY":
        rendered = f"approx. {rendered}"
    note = child_text(node, "NOTE")
    if note and note.lower() not in rendered.lower():
        rendered += f" ({note})"
    return rendered


def _format_document(node: Element) -> str:
    kind = child_text(node, "TYPE_OF_DOCUMENT")
    kind2 = child_text(node, "TYPE_OF_DOCUMENT2")
    label = " / ".join(part for part in (kind, kind2) if part) or "ID"
    number = child_text(node, "NUMBER")
    if not kind and not kind2 and not number:
        return ""

    rendered = f"{label}: {number}" if number else label
    country = child_text(node, "ISSUING_COUNTRY") or child_text(node, "COUNTRY_OF_ISSUE")
    if country:
        rendered += f" ({country})"

    issued_parts = [
        child_text(node, "DATE_OF_ISSUE"),
        child_text(node, "CITY_OF_ISSUE"),
    ]
    issued = _PART_SEP.join(part for part in issued_parts if part)
    if issued:
        rendered += f" [issued {issued}]"
    expiry = child_text(node, "DATE_OF_EXPIRY")
    if expiry:
        rendered += f" [expires {expiry}]"
    note = child_text(node, "NOTE")
    if note:
        rendered += f" ({note})"
    return rendered


def _join_location(node: Element, keys: tuple[str, ...]) -> str:
    pieces: list[str] = []
    for key in keys:
        value = child_text(node, key)
        if value and value not in pieces:
            pieces.append(value)
    return _PART_SEP.join(pieces)


def _values(parent: Element, container: str) -> list[str]:
    """Collect the non-empty ``<VALUE>`` texts under every ``<container>`` child."""
    out: list[str] = []
    for node in children(parent, container):
        for value in children(node, "VALUE"):
            text = (value.text or "").strip()
            if text:
                out.append(text)
    return out
