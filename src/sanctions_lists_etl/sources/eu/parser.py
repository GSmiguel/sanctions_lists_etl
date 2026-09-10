"""Stream the EU FSF full XML into flat :class:`SanctionEntity` rows.

The EU export is much flatter than the OFAC advanced format: there are no
reference tables, and every ``<sanctionEntity>`` carries all of its names,
birth dates, addresses, identifications and citizenships inline as child
elements with the values held in attributes.  A single ``iterparse`` pass with
``elem.clear()`` after each entity is enough.

Namespace: ``http://eu.europa.ec/fpi/fsd/export`` (handled namespace-agnostically
via :mod:`sanctions_lists_etl.common.xmlutils`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable
from xml.etree.ElementTree import Element, iterparse

log = logging.getLogger(__name__)

from ...common.xmlutils import child_text, children, first_child, localname
from .columns import COLUMNS

_LIST_SEP = "; "
_PART_SEP = ", "
# countryDescription / city placeholders that carry no information.
_EMPTY_VALUES = {"", "-", "unknown", "undetermined", "not specified"}

# subjectType/@code -> the vocabulary shared with the OFAC export.
_TYPE_BY_CODE = {"person": "Individual", "enterprise": "Entity"}

_GENDER = {"m": "Male", "f": "Female"}

_CONTACT_BUCKET = {
    "EMAIL": "emails",
    "PHONE": "phones",
    "FAX": "phones",
    "WEB": "websites",
}


@dataclass
class SanctionEntity:
    eu_reference_number: str
    logical_id: str = ""
    un_id: str = ""
    party_type: str = "Unknown"
    subject_code: str = ""
    primary_name: str = ""
    aliases: list[str] = field(default_factory=list)
    birth_dates: list[str] = field(default_factory=list)
    birth_places: list[str] = field(default_factory=list)
    citizenships: list[str] = field(default_factory=list)
    genders: list[str] = field(default_factory=list)
    titles: list[str] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)
    address_countries: list[str] = field(default_factory=list)
    addresses: list[str] = field(default_factory=list)
    documents: list[str] = field(default_factory=list)
    programmes: list[str] = field(default_factory=list)
    regulations: list[str] = field(default_factory=list)
    listed_on: list[str] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    websites: list[str] = field(default_factory=list)
    remarks: list[str] = field(default_factory=list)

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


def parse_eu_fsf(
    source: Path | str,
    *,
    subject_types: Iterable[str] | None = None,
) -> list[SanctionEntity]:
    """Parse ``source`` and return one :class:`SanctionEntity` per listed party.

    ``subject_types`` optionally restricts the output to the given
    ``subjectType/@code`` values (``"person"`` and/or ``"enterprise"``).
    """
    keep = {code.lower() for code in subject_types} if subject_types is not None else None

    records: list[SanctionEntity] = []
    seen = 0

    log.info("parsing %s", source)
    for _, elem in iterparse(str(source), events=("end",)):
        if localname(elem.tag) != "sanctionEntity":
            continue
        seen += 1
        record = _build_entity(elem)
        if keep is None or record.subject_code in keep:
            records.append(record)
        elem.clear()
        if seen % 2000 == 0:
            log.info("  %d entities parsed (%d kept)", seen, len(records))

    log.info("parsed %d entities (%d kept)", seen, len(records))
    return records


def rows_from_records(records: Iterable[SanctionEntity]) -> list[dict[str, str]]:
    return [record.to_row() for record in records]


# --------------------------------------------------------------------------- #
# entity assembly
# --------------------------------------------------------------------------- #
def _build_entity(entity: Element) -> SanctionEntity:
    record = SanctionEntity(
        eu_reference_number=entity.get("euReferenceNumber", ""),
        logical_id=entity.get("logicalId", ""),
        un_id=entity.get("unitedNationId", ""),
    )

    subject = first_child(entity, "subjectType")
    if subject is not None:
        record.subject_code = (subject.get("code") or "").lower()
        record.party_type = _TYPE_BY_CODE.get(record.subject_code, record.subject_code.title())

    _resolve_names(entity, record)

    for citizenship in children(entity, "citizenship"):
        country = _clean(citizenship.get("countryDescription"))
        if country:
            record.citizenships.append(country)

    for birthdate in children(entity, "birthdate"):
        rendered = _format_birthdate(birthdate)
        if rendered:
            record.birth_dates.append(rendered)
        place = _format_place(birthdate)
        if place:
            record.birth_places.append(place)

    for address in children(entity, "address"):
        _apply_address(address, record)

    for document in children(entity, "identification"):
        rendered = _format_document(document)
        if rendered:
            record.documents.append(rendered)

    _apply_regulation(entity, record)

    # designationDate is the cleanest "listed on"; fall back to the regulation
    # publication dates gathered in _apply_regulation.
    designation = entity.get("designationDate")
    if designation:
        record.listed_on.insert(0, designation)
    record.listed_on = record.listed_on[:1]

    for remark in children(entity, "remark"):
        text = (remark.text or "").strip()
        if text:
            record.remarks.append(text)
    details = (entity.get("designationDetails") or "").strip()
    if details:
        record.remarks.append(details)

    return record


def _resolve_names(entity: Element, record: SanctionEntity) -> None:
    """Pick a primary name and collect the rest as aliases.

    The EU list has no explicit "primary" flag, but aliases are assigned
    ``logicalId``s in the order they were ever added, so the lowest id is the
    original listing name.  When that name is in a non-Latin script and a
    Latin-script alias exists, prefer the lowest-id Latin one for readability.
    """
    aliases: list[tuple[int, str, str]] = []  # (logical_id, whole_name, language)
    for alias in children(entity, "nameAlias"):
        whole = (alias.get("wholeName") or "").strip()
        if not whole:
            first = (alias.get("firstName") or "").strip()
            last = (alias.get("lastName") or "").strip()
            whole = " ".join(part for part in (first, last) if part)
        if not whole:
            continue
        lid = alias.get("logicalId") or ""
        aliases.append((int(lid) if lid.isdigit() else 2**63, whole, (alias.get("nameLanguage") or "").upper()))

        gender = _GENDER.get((alias.get("gender") or "").lower())
        if gender:
            record.genders.append(gender)
        title = (alias.get("title") or "").strip()
        if title:
            record.titles.append(title)
        function = (alias.get("function") or "").strip()
        if function:
            record.functions.append(function)

    if not aliases:
        return

    aliases.sort(key=lambda item: item[0])
    latin = [item for item in aliases if _is_latin(item[1])]
    primary = (latin or aliases)[0]
    record.primary_name = primary[1]

    for lid, whole, language in aliases:
        if (lid, whole, language) == primary:
            continue
        if language and language != "EN":
            record.aliases.append(f"{whole} ({language})")
        else:
            record.aliases.append(whole)


def _apply_address(address: Element, record: SanctionEntity) -> None:
    country = _clean(address.get("countryDescription"))
    if country:
        record.address_countries.append(country)

    parts = [
        address.get("street"),
        f"PO Box {address.get('poBox')}" if (address.get("poBox") or "").strip() else "",
        address.get("zipCode"),
        address.get("city"),
        address.get("region"),
        address.get("place"),
        country,
    ]
    rendered = _PART_SEP.join(part.strip() for part in parts if part and part.strip())
    remark = child_text(address, "remark")
    if rendered and remark:
        rendered = f"{rendered} ({remark})"
    elif remark and not rendered:
        rendered = remark
    if rendered:
        record.addresses.append(rendered)

    for contact in children(address, "contactInfo"):
        bucket = _CONTACT_BUCKET.get((contact.get("key") or "").upper())
        value = (contact.get("value") or "").strip()
        if bucket and value:
            getattr(record, bucket).append(value)


def _apply_regulation(entity: Element, record: SanctionEntity) -> None:
    regulation = first_child(entity, "regulation")
    if regulation is not None:
        programme = (regulation.get("programme") or "").strip()
        if programme:
            record.programmes.append(programme)
        record.regulations.append(_format_regulation(regulation))
        pub = regulation.get("publicationDate")
        if pub:
            record.listed_on.append(pub)

    # Every child element also references the regulation that set it; keep the
    # distinct titles so the row shows the full amendment trail.
    for summary in entity.iter():
        if localname(summary.tag) != "regulationSummary":
            continue
        title = _format_regulation(summary)
        if title:
            record.regulations.append(title)
        pub = summary.get("publicationDate")
        if pub:
            record.listed_on.append(pub)

    record.listed_on.sort()


# --------------------------------------------------------------------------- #
# small formatters
# --------------------------------------------------------------------------- #
def _format_birthdate(birthdate: Element) -> str:
    iso = (birthdate.get("birthdate") or "").strip()
    if iso:
        return iso

    year_from = (birthdate.get("yearRangeFrom") or "").strip()
    year_to = (birthdate.get("yearRangeTo") or "").strip()
    if year_from and year_to:
        return year_from if year_from == year_to else f"{year_from}-{year_to}"
    if year_from or year_to:
        return year_from or year_to

    year = (birthdate.get("year") or "").strip()
    if not year or year == "0":
        return ""
    out = year
    month = (birthdate.get("monthOfYear") or "").strip()
    if month and month != "0":
        out += f"-{int(month):02d}"
        day = (birthdate.get("dayOfMonth") or "").strip()
        if day and day != "0":
            out += f"-{int(day):02d}"
    return out


def _format_place(node: Element) -> str:
    pieces: list[str] = []
    for key in ("place", "city", "region", "countryDescription"):
        value = _clean(node.get(key))
        if value and value not in pieces:
            pieces.append(value)
    rendered = _PART_SEP.join(pieces)
    # A bare <remark> on an otherwise-empty birthdate is usually a note about
    # the date ("hijri calendar", "between 1953 and 1958"), not a place — only
    # keep it when it annotates a real location.
    remark = child_text(node, "remark")
    if rendered and remark and remark not in rendered:
        rendered = f"{rendered} ({remark})"
    return rendered


def _format_document(document: Element) -> str:
    kind = (document.get("identificationTypeDescription") or "ID").strip()
    number = (document.get("number") or document.get("latinNumber") or "").strip()
    if not number:
        return ""
    rendered = f"{kind}: {number}"
    country = _clean(document.get("countryDescription"))
    if country:
        rendered += f" ({country})"
    name_on = (document.get("nameOnDocument") or "").strip()
    if name_on:
        rendered += f" — {name_on}"
    flags = [
        label
        for attr, label in (
            ("knownExpired", "expired"),
            ("knownFalse", "reported false"),
            ("reportedLost", "reported lost"),
            ("revokedByIssuer", "revoked"),
        )
        if (document.get(attr) or "").lower() == "true"
    ]
    if flags:
        rendered += f" [{', '.join(flags)}]"
    return rendered


def _format_regulation(node: Element) -> str:
    title = (node.get("numberTitle") or "").strip()
    if not title:
        return ""
    date = (node.get("publicationDate") or "").strip()
    return f"{title} ({date})" if date else title


def _clean(value: str | None) -> str:
    value = (value or "").strip()
    return "" if value.lower() in _EMPTY_VALUES else value


def _is_latin(text: str) -> bool:
    """True when the alphabetic characters in ``text`` are (near) all Latin.

    Covers Basic Latin, Latin-1 Supplement, Latin Extended-A/-B/-Additional —
    enough to tell a transliterated name from Cyrillic / Arabic / Han script.
    """
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return True
    latin = sum(1 for ch in letters if ord(ch) < 0x250 or 0x1E00 <= ord(ch) <= 0x1EFF)
    return latin / len(letters) >= 0.8
