"""Stream the UK Sanctions List XML into flat :class:`SanctionParty` rows.

The FCDO export is flat like the UN one — no reference tables.  The document is

    <Designations>
      <Designation>...</Designation>
      ...
    </Designations>

and every ``<Designation>`` carries all of its names, aliases, addresses and
type-specific details (individual / entity / ship) inline as child elements whose
values are element *text*.  A single ``iterparse`` pass with ``elem.clear()``
after each designation is enough; the party type comes from the
``<IndividualEntityShip>`` child, so no forward join is needed.
"""

from __future__ import annotations

import io
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from xml.etree.ElementTree import Element, iterparse

log = logging.getLogger(__name__)

from ...common.records import flatten_row
from ...common.xmlutils import child_text, children, first_child, localname
from .columns import COLUMNS

_LIST_SEP = "; "
_PART_SEP = ", "

# <IndividualEntityShip> text -> the vocabulary shared with the OFAC/EU/UN exports.
# "Ship" is mapped to "Vessel" to match the OFAC party-type wording.
_TYPE_BY_KIND = {"Individual": "Individual", "Entity": "Entity", "Ship": "Vessel"}
# ... and the filter tokens (--individuals-only / --entities-only / --no-ships).
_FILTER_TOKEN = {"Individual": "INDIVIDUAL", "Entity": "ENTITY", "Vessel": "SHIP"}

_ADDRESS_KEYS = (
    "AddressLine1",
    "AddressLine2",
    "AddressLine3",
    "AddressLine4",
    "AddressLine5",
    "AddressLine6",
    "AddressPostalCode",
    "AddressCountry",
)

# The FCDO mixes an INTERPOL notice pointer into the free-text OtherInformation
# field; it carries no information (the UN reference is captured structurally in
# un_reference_number), so it is scrubbed from remarks.  Shapes seen: a "Photo
# available for inclusion in the ... Special Notice" sentence anywhere in the
# text, and a trailing "... Special Notice[ web link]: <url> [click here]" or a
# bare "web link: <interpol url>".  The "INTERPOL-UN" token is written variously
# "INTERPOL-UN", "INTERPOLUN" or "INTERPOL UN".  An interior "INTERPOL Special
# Notice contains biometric information" sentence is genuine and left alone.
_INTERPOL = r"INTERPOL[- ]?UN(?:SC)?(?: Security Council)?"
# FCDO free text drops spaces at random ("forinclusion", "itsterritory"), so the
# connective words are matched with flexible whitespace.
_PHOTO = (
    r"(?:Photo(?:graph)?|Picture)s?(?: and fingerprints)?(?: is| are)?\s*"
    r"(?:available\s*for\s*inclusion\s*in|included\s*in)\s*(?:the\s*)?"
)
# The "Photo(s) ... available for inclusion in the ... Special Notice." sentence
# can sit anywhere (real information often follows it), so it is removed on its
# own before the trailing pointer is cut.
_PHOTO_SENTENCE = re.compile(r"\s*" + _PHOTO + _INTERPOL + r" Special Notice\.?", re.IGNORECASE)
# The notice pointer always sits at the end of the field and the FCDO data
# routinely injects stray spaces into the URL, so once a trailing marker is seen
# everything from it to the end is dropped (DOTALL ``.*$``).
_INTERPOL_TAILS = (
    re.compile(
        r"[\s.]*" + _INTERPOL + r" Special Notice(?: web ?link)?\s*:?.*$",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(r"[\s.]*web ?link\s*:\s*https?://.*$", re.IGNORECASE | re.DOTALL),
    re.compile(r"\s*\(?https?://\S*interpol\.int\S*\)?", re.IGNORECASE),
)
_ORPHAN_PUNCT = re.compile(r"\s+([.,;])")


def _clean_other_information(text: str) -> str:
    text = _PHOTO_SENTENCE.sub("", " ".join(text.split()))
    for tail in _INTERPOL_TAILS:
        text = tail.sub("", text)
    text = _ORPHAN_PUNCT.sub(r"\1", text)
    return re.sub(r"\s{2,}", " ", text).strip(" .,;:")


@dataclass
class SanctionParty:
    uk_unique_id: str
    ofsi_group_id: str = ""
    un_reference_number: str = ""
    party_type: str = "Unknown"
    primary_name: str = ""
    name_original_script: str = ""
    aliases: list[str] = field(default_factory=list)
    titles: list[str] = field(default_factory=list)
    birth_dates: list[str] = field(default_factory=list)
    birth_places: list[str] = field(default_factory=list)
    nationalities: list[str] = field(default_factory=list)
    genders: list[str] = field(default_factory=list)
    positions: list[str] = field(default_factory=list)
    address_countries: list[str] = field(default_factory=list)
    addresses: list[str] = field(default_factory=list)
    documents: list[str] = field(default_factory=list)
    regime_name: str = ""
    designation_source: str = ""
    sanctions_imposed: list[str] = field(default_factory=list)
    listed_on: list[str] = field(default_factory=list)
    last_updated: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    websites: list[str] = field(default_factory=list)
    entity_type: list[str] = field(default_factory=list)
    parent_companies: list[str] = field(default_factory=list)
    subsidiaries: list[str] = field(default_factory=list)
    vessel_info: str = ""
    statement_of_reasons: str = ""
    other_information: str = ""

    def to_row(self) -> dict[str, str]:
        return flatten_row(self, COLUMNS)


def parse_uk_sanctions(
    source: bytes,
    *,
    subject_types: Iterable[str] | None = None,
) -> list[SanctionParty]:
    """Parse ``source`` (raw XML bytes) and return one :class:`SanctionParty` per
    designation.

    ``subject_types`` optionally restricts the output to ``"INDIVIDUAL"``,
    ``"ENTITY"`` and/or ``"SHIP"`` (case-insensitive).
    """
    keep = {t.upper() for t in subject_types} if subject_types is not None else None

    records: list[SanctionParty] = []
    seen = 0

    log.info("parsing %d bytes of XML", len(source))
    for _, elem in iterparse(io.BytesIO(source), events=("end",)):
        if localname(elem.tag) != "Designation":
            continue
        seen += 1
        record = _build_party(elem)
        if keep is None or _FILTER_TOKEN.get(record.party_type, "") in keep:
            records.append(record)
        elem.clear()
        if seen % 2000 == 0:
            log.info("  %d designations parsed (%d kept)", seen, len(records))

    log.info("parsed %d designations (%d kept)", seen, len(records))
    return records


def rows_from_records(records: Iterable[SanctionParty]) -> list[dict[str, str]]:
    return [record.to_row() for record in records]


# --------------------------------------------------------------------------- #
# party assembly
# --------------------------------------------------------------------------- #
def _build_party(desig: Element) -> SanctionParty:
    kind = child_text(desig, "IndividualEntityShip")
    record = SanctionParty(
        uk_unique_id=child_text(desig, "UniqueID"),
        ofsi_group_id=child_text(desig, "OFSIGroupID"),
        un_reference_number=child_text(desig, "UNReferenceNumber"),
        party_type=_TYPE_BY_KIND.get(kind, kind or "Unknown"),
        regime_name=child_text(desig, "RegimeName"),
        designation_source=child_text(desig, "DesignationSource"),
        statement_of_reasons=" ".join(child_text(desig, "UKStatementofReasons").split()),
    )

    record.primary_name, record.aliases, record.name_original_script = _resolve_names(desig)

    record.titles = _texts(desig, "Titles", "Title")
    record.sanctions_imposed = [
        piece.strip() for piece in child_text(desig, "SanctionsImposed").split("|") if piece.strip()
    ]
    designated = _to_iso(child_text(desig, "DateDesignated"))
    if designated:
        record.listed_on.append(designated)
    updated = _to_iso(child_text(desig, "LastUpdated"))
    if updated:
        record.last_updated.append(updated)

    for address in _iter(desig, "Addresses", "Address"):
        country = child_text(address, "AddressCountry")
        if country:
            record.address_countries.append(country)
        rendered = _join(address, _ADDRESS_KEYS)
        if rendered:
            record.addresses.append(rendered)

    record.websites = _texts(desig, "Websites", "Website")
    record.phones = _texts(desig, "PhoneNumbers", "PhoneNumber")
    record.emails = _texts(desig, "EmailAddresses", "EmailAddress")

    record.other_information = _clean_other_information(child_text(desig, "OtherInformation"))

    _apply_individual(desig, record)
    _apply_entity(desig, record)
    _apply_ship(desig, record)

    return record


def _resolve_names(desig: Element) -> tuple[str, list[str], str]:
    primary = ""
    aliases: list[str] = []
    names_parent = first_child(desig, "Names")
    for name_el in children(names_parent, "Name") if names_parent is not None else []:
        assembled = _assemble_name(name_el)
        if not assembled:
            continue
        kind = " ".join(child_text(name_el, "NameType").split()).lower()
        if kind == "primary name":
            if not primary:
                primary = assembled
            else:  # extra primary rows are alternate spellings
                aliases.append(f"{assembled} (primary name)")
        elif kind == "primary name variation":
            aliases.append(f"{assembled} (primary name variation)")
        else:
            strength = child_text(name_el, "AliasStrength").lower()
            aliases.append(f"{assembled} (low quality)" if "low" in strength else assembled)

    if not primary and aliases:
        primary = aliases.pop(0).rsplit(" (", 1)[0]

    scripts = [
        text
        for parent in children(desig, "NonLatinNames")
        for node in children(parent, "NonLatinName")
        if (text := child_text(node, "NameNonLatinScript"))
    ]
    return primary, aliases, _LIST_SEP.join(dict.fromkeys(scripts))


def _assemble_name(name_el: Element) -> str:
    parts = [child_text(name_el, f"Name{i}") for i in range(1, 7)]
    return " ".join(" ".join(part for part in parts if part).split())


def _apply_individual(desig: Element, record: SanctionParty) -> None:
    individual = _first(desig, "IndividualDetails", "Individual")
    if individual is None:
        return

    record.birth_dates = [
        rendered
        for node in _iter(individual, "DOBs", "DOB")
        if (rendered := _format_dob(node.text or ""))
    ]
    record.nationalities = _texts(individual, "Nationalities", "Nationality")
    record.genders = _texts(individual, "Genders", "Gender")
    record.positions = _texts(individual, "Positions", "Position")

    for location in individual.findall("BirthDetails/Location"):
        rendered = _join(location, ("TownOfBirth", "CountryOfBirth"))
        if rendered:
            record.birth_places.append(rendered)

    for passport in individual.findall("PassportDetails/Passport"):
        info = child_text(passport, "PassportAdditionalInformation")
        number = child_text(passport, "PassportNumber")
        rendered = info or (f"Passport: {number}" if number else "")
        if rendered:
            record.documents.append(rendered)

    for national_id in individual.findall("NationalIdentifierDetails/NationalIdentifier"):
        number = child_text(national_id, "NationalIdentifierNumber")
        info = " ".join(child_text(national_id, "NationalIdentifierAdditionalInformation").split())
        if not number and not info:
            continue
        rendered = f"National ID: {number}" if number else "National ID"
        if info:
            rendered += f" ({info})"
        record.documents.append(rendered)


def _apply_entity(desig: Element, record: SanctionParty) -> None:
    entity = _first(desig, "EntityDetails", "Entity")
    if entity is None:
        return
    record.entity_type = _texts(entity, "TypeOfEntities", "TypeOfEntity")
    record.parent_companies = _texts(entity, "ParentCompanies", "ParentCompany")
    record.subsidiaries = _texts(entity, "Subsidiaries", "Subsidiary")
    for value in _texts(entity, "BusinessRegistrationNumbers", "BusinessRegistrationNumber"):
        record.documents.append(f"Business reg.: {value}")


def _apply_ship(desig: Element, record: SanctionParty) -> None:
    ship = _first(desig, "ShipDetails", "Ship")
    if ship is None:
        return
    for value in _texts(ship, "IMONumbers", "IMONumber"):
        digits = value[3:].strip() if value.upper().startswith("IMO") else value
        record.documents.append(f"IMO {digits}")
    for flag in _texts(ship, "CurrentBelievedFlagOfShips", "CurrentBelievedFlagOfShip"):
        record.address_countries.append(flag)
    record.positions.extend(_texts(ship, "CurrentOwnerOperators", "CurrentOwnerOperator"))

    pieces: list[str] = []
    for label, container, item in (
        ("Type", "TypeOfShipDetails", "TypeOfShip"),
        ("Year built", "YearsBuilt", "YearBuilt"),
        ("Tonnage", "TonnageOfShipDetails", "TonnageOfShip"),
        ("Length", "LengthOfShipDetails", "LengthOfShip"),
        ("Previous flag", "PreviousFlags", "PreviousFlag"),
    ):
        joined = _PART_SEP.join(_texts(ship, container, item))
        if joined:
            pieces.append(f"{label}: {joined}")
    record.vessel_info = "; ".join(pieces)


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def _first(parent: Element, container: str, name: str) -> Element | None:
    wrapper = first_child(parent, container)
    return first_child(wrapper, name) if wrapper is not None else None


def _iter(parent: Element, container: str, name: str) -> list[Element]:
    out: list[Element] = []
    for wrapper in children(parent, container):
        out.extend(children(wrapper, name))
    return out


def _texts(parent: Element, container: str, name: str) -> list[str]:
    return [
        (node.text or "").strip()
        for node in _iter(parent, container, name)
        if (node.text or "").strip()
    ]


def _join(node: Element, keys: tuple[str, ...]) -> str:
    pieces: list[str] = []
    for key in keys:
        value = child_text(node, key)
        if value and value not in pieces:
            pieces.append(value)
    return _PART_SEP.join(pieces)


def _to_iso(raw: str) -> str:
    match = re.match(r"(\d{2})/(\d{2})/(\d{4})$", raw.strip())
    return f"{match[3]}-{match[2]}-{match[1]}" if match else raw.strip()


def _format_dob(raw: str) -> str:
    """Render a UK ``DOB`` value.

    The feed uses ``dd/mm/yyyy`` with the literal placeholders ``dd`` / ``mm``
    when the day or month is unknown (e.g. ``dd/mm/1969`` = year only), plain
    ``yyyy`` for a bare year, and — very rarely — a malformed value that is
    passed through untouched.
    """
    raw = raw.strip()
    if not raw:
        return ""
    parts = raw.split("/")
    if len(parts) == 3:
        day, month, year = (p.strip() for p in parts)
        if year.isdigit() and len(year) == 4:
            if day.isdigit() and month.isdigit():
                return f"{year}-{int(month):02d}-{int(day):02d}"
            if month.isdigit():
                return f"{year}-{int(month):02d}"
            return year
        return raw
    if raw.isdigit() and len(raw) == 4:
        return raw
    return raw
