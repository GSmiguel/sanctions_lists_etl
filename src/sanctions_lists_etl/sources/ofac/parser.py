"""Stream the SDN advanced XML into flat :class:`PartyRecord` rows.

The file is laid out as: ``ReferenceValueSets`` -> ``Locations`` ->
``IDRegDocuments`` -> ``DistinctParties`` -> ``SanctionsEntries``.  Locations and
ID documents are needed while reading a party; sanctions entries come afterwards
and are joined back onto the already-built records by profile id.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable
from xml.etree.ElementTree import Element, iterparse

log = logging.getLogger(__name__)

from ...common.xmlutils import (
    child_text,
    children,
    first_child,
    format_date_period,
    format_ymd,
    localname,
)
from .columns import COLUMNS
from .references import ReferenceData, parse_reference_data

# Feature type ids with dedicated columns (stable in the OFAC schema).
FEATURE_BIRTHDATE = "8"
FEATURE_BIRTHPLACE = "9"
FEATURE_NATIONALITY = "10"
FEATURE_CITIZENSHIP = "11"
FEATURE_WEBSITE = "14"
FEATURE_EMAIL = "21"
FEATURE_LOCATION = "25"
FEATURE_TITLE = "26"
FEATURE_GENDER = "224"

_LIST_SEP = "; "
_UNKNOWN_COUNTRIES = {"undetermined", "unknown"}
_ADDRESS_PART_ORDER = (
    "ADDRESS1",
    "ADDRESS2",
    "ADDRESS3",
    "REGION",
    "CITY",
    "STATE/PROVINCE",
    "POSTAL CODE",
)


@dataclass
class PartyRecord:
    fixed_ref: str
    party_type: str = "Unknown"
    primary_name: str = ""
    aliases: list[str] = field(default_factory=list)
    birth_dates: list[str] = field(default_factory=list)
    birth_places: list[str] = field(default_factory=list)
    nationalities: list[str] = field(default_factory=list)
    citizenships: list[str] = field(default_factory=list)
    genders: list[str] = field(default_factory=list)
    titles: list[str] = field(default_factory=list)
    address_countries: list[str] = field(default_factory=list)
    addresses: list[str] = field(default_factory=list)
    documents: list[str] = field(default_factory=list)
    programs: list[str] = field(default_factory=list)
    sanctions_lists: list[str] = field(default_factory=list)
    listed_on: list[str] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    websites: list[str] = field(default_factory=list)
    crypto_addresses: list[str] = field(default_factory=list)
    other_features: list[str] = field(default_factory=list)

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


def parse_sdn_advanced(
    source: Path | str,
    *,
    party_types: Iterable[str] | None = None,
) -> list[PartyRecord]:
    """Parse ``source`` and return one :class:`PartyRecord` per sanctioned party.

    ``party_types`` optionally restricts the output (e.g. ``{"Individual",
    "Entity"}``); by default every party type is kept.
    """
    keep = set(party_types) if party_types is not None else None

    ref: ReferenceData | None = None
    locations: dict[str, str] = {}
    location_countries: dict[str, str] = {}
    docs_by_identity: dict[str, list[str]] = {}
    records: dict[str, PartyRecord] = {}
    seen_parties = 0
    seen_entries = 0

    log.info("parsing %s", source)
    for _, elem in iterparse(str(source), events=("end",)):
        tag = localname(elem.tag)

        if tag == "ReferenceValueSets":
            ref = parse_reference_data(elem)
            log.info(
                "  reference tables loaded (%d countries, %d feature types, %d lists)",
                len(ref.country),
                len(ref.feature_type),
                len(ref.list_name),
            )
            elem.clear()
        elif tag == "Location":
            assert ref is not None
            loc_id = elem.get("ID")
            text, country = _format_location(elem, ref)
            if loc_id is not None:
                locations[loc_id] = text
                if country:
                    location_countries[loc_id] = country
            elem.clear()
        elif tag == "IDRegDocument":
            assert ref is not None
            identity_id = elem.get("IdentityID")
            rendered = _format_document(elem, ref)
            if identity_id and rendered:
                docs_by_identity.setdefault(identity_id, []).append(rendered)
            elem.clear()
        elif tag == "DistinctParty":
            assert ref is not None
            record = _build_party(elem, ref, locations, location_countries, docs_by_identity)
            if record is not None and (keep is None or record.party_type in keep):
                records[elem.get("FixedRef")] = record
            elem.clear()
            seen_parties += 1
            if seen_parties % 2000 == 0:
                log.info("  %d parties parsed (%d kept)", seen_parties, len(records))
        elif tag == "SanctionsEntry":
            assert ref is not None
            _attach_sanctions_entry(elem, ref, records)
            elem.clear()
            seen_entries += 1
            if seen_entries % 5000 == 0:
                log.info("  %d sanctions entries joined", seen_entries)

    log.info(
        "parsed %d parties (%d kept), %d sanctions entries",
        seen_parties,
        len(records),
        seen_entries,
    )
    return list(records.values())


def rows_from_records(records: Iterable[PartyRecord]) -> list[dict[str, str]]:
    return [record.to_row() for record in records]


# --------------------------------------------------------------------------- #
# party assembly
# --------------------------------------------------------------------------- #
def _build_party(
    party: Element,
    ref: ReferenceData,
    locations: dict[str, str],
    location_countries: dict[str, str],
    docs_by_identity: dict[str, list[str]],
) -> PartyRecord | None:
    profile = first_child(party, "Profile")
    if profile is None:
        return None

    record = PartyRecord(fixed_ref=party.get("FixedRef", ""))
    record.party_type = ref.party_type_for_subtype(profile.get("PartySubTypeID"))

    identity = first_child(profile, "Identity")
    if identity is not None:
        record.primary_name, record.aliases = _resolve_names(identity, ref)
        identity_id = identity.get("ID")
        if identity_id in docs_by_identity:
            record.documents = docs_by_identity.pop(identity_id)

    for feature in children(profile, "Feature"):
        _apply_feature(feature, ref, record, locations, location_countries)

    return record


def _resolve_names(identity: Element, ref: ReferenceData) -> tuple[str, list[str]]:
    group_type: dict[str, str] = {}
    groups = first_child(identity, "NamePartGroups")
    if groups is not None:
        for master in children(groups, "MasterNamePartGroup"):
            npg = first_child(master, "NamePartGroup")
            if npg is not None:
                group_type[npg.get("ID")] = ref.name_part_type.get(
                    npg.get("NamePartTypeID"), ""
                )

    primary = ""
    aliases: list[str] = []
    for alias in children(identity, "Alias"):
        alias_type = ref.alias_type.get(alias.get("AliasTypeID"), "")
        is_primary = alias.get("Primary") == "true"
        low_quality = alias.get("LowQuality") == "true"
        for rendered in _rendered_names(alias, group_type):
            if is_primary and not primary:
                primary = rendered
                continue
            label = alias_type or "alias"
            if low_quality:
                label += ", weak"
            aliases.append(f"{rendered} ({label})")

    if not primary and aliases:
        primary = aliases.pop(0).rsplit(" (", 1)[0]
    return primary, aliases


def _rendered_names(alias: Element, group_type: dict[str, str]) -> list[str]:
    documented = children(alias, "DocumentedName")
    # Prefer the base ("status 1") rendering, then any others (scripts, variants).
    documented.sort(key=lambda d: d.get("DocNameStatusID") != "1")
    rendered: list[str] = []
    for doc in documented:
        parts: list[tuple[str, str]] = []
        for part in children(doc, "DocumentedNamePart"):
            value = first_child(part, "NamePartValue")
            if value is None or not (value.text or "").strip():
                continue
            parts.append((group_type.get(value.get("NamePartGroupID"), ""), value.text.strip()))
        name = _join_name_parts(parts)
        if name:
            rendered.append(name)
    return rendered


def _join_name_parts(parts: list[tuple[str, str]]) -> str:
    if not parts:
        return ""
    surnames = [value for kind, value in parts if kind == "Last Name"]
    others = [value for kind, value in parts if kind != "Last Name"]
    if surnames and others:
        return f"{' '.join(surnames)}, {' '.join(others)}"
    return " ".join(value for _, value in parts)


# --------------------------------------------------------------------------- #
# features
# --------------------------------------------------------------------------- #
def _apply_feature(
    feature: Element,
    ref: ReferenceData,
    record: PartyRecord,
    locations: dict[str, str],
    location_countries: dict[str, str],
) -> None:
    type_id = feature.get("FeatureTypeID")
    type_name = ref.feature_type.get(type_id, f"Feature {type_id}")
    values: list[str] = []
    for version in children(feature, "FeatureVersion"):
        values.extend(_feature_version_values(version, ref, locations))
        for version_location in children(version, "VersionLocation"):
            country = location_countries.get(version_location.get("LocationID"))
            if country:
                record.address_countries.append(country)

    if not values:
        return

    bucket = {
        FEATURE_BIRTHDATE: record.birth_dates,
        FEATURE_BIRTHPLACE: record.birth_places,
        FEATURE_NATIONALITY: record.nationalities,
        FEATURE_CITIZENSHIP: record.citizenships,
        FEATURE_GENDER: record.genders,
        FEATURE_TITLE: record.titles,
        FEATURE_EMAIL: record.emails,
        FEATURE_WEBSITE: record.websites,
        FEATURE_LOCATION: record.addresses,
    }.get(type_id)

    if bucket is not None:
        bucket.extend(values)
    elif type_name.startswith("Digital Currency Address"):
        currency = type_name.split("-")[-1].strip()
        record.crypto_addresses.extend(f"{currency}: {value}" for value in values)
    else:
        clean = type_name.rstrip(" -:")
        record.other_features.extend(f"{clean}: {value}" for value in values)


def _feature_version_values(
    version: Element, ref: ReferenceData, locations: dict[str, str]
) -> list[str]:
    values: list[str] = []
    for child in version:
        name = localname(child.tag)
        if name == "VersionLocation":
            address = locations.get(child.get("LocationID"))
            if address:
                values.append(address)
        elif name == "DatePeriod":
            rendered = format_date_period(child)
            if rendered:
                values.append(rendered)
        elif name == "VersionDetail":
            text = (child.text or "").strip()
            if text:
                values.append(text)
            else:
                ref_id = child.get("DetailReferenceID")
                if ref_id in ref.detail_reference:
                    values.append(ref.detail_reference[ref_id])
    return values


# --------------------------------------------------------------------------- #
# locations & documents
# --------------------------------------------------------------------------- #
def _format_location(location: Element, ref: ReferenceData) -> tuple[str, str]:
    ordered: dict[str, str] = {}
    for part in children(location, "LocationPart"):
        kind = ref.loc_part_type.get(part.get("LocPartTypeID"), part.get("LocPartTypeID", ""))
        value_el = first_child(part, "LocationPartValue")
        value = child_text(value_el, "Value") if value_el is not None else ""
        if value:
            ordered.setdefault(kind, value)

    country = ""
    country_el = first_child(location, "LocationCountry")
    if country_el is not None:
        country = ref.country.get(country_el.get("CountryID"), "")
    if not country:
        area_el = first_child(location, "LocationAreaCode")
        if area_el is not None:
            country = ref.area_code_country.get(area_el.get("AreaCodeID"), "")
    if country.lower() in _UNKNOWN_COUNTRIES:
        country = ""

    pieces = [ordered[key] for key in _ADDRESS_PART_ORDER if key in ordered]
    pieces.extend(value for key, value in ordered.items() if key not in _ADDRESS_PART_ORDER)
    if country:
        pieces.append(country)
    return ", ".join(pieces), country


def _format_document(document: Element, ref: ReferenceData) -> str:
    number = child_text(document, "IDRegistrationNo")
    if not number:
        return ""
    rendered = f"{ref.id_reg_doc_type.get(document.get('IDRegDocTypeID'), 'ID')}: {number}"
    country = ref.country.get(document.get("IssuedBy-CountryID"), "")
    if country:
        rendered += f" ({country})"
    authority = child_text(document, "IssuingAuthority")
    if authority:
        rendered += f" - {authority}"
    return rendered


# --------------------------------------------------------------------------- #
# sanctions entries
# --------------------------------------------------------------------------- #
def _attach_sanctions_entry(
    entry: Element, ref: ReferenceData, records: dict[str, PartyRecord]
) -> None:
    record = records.get(entry.get("ProfileID"))
    if record is None:
        return

    list_name = ref.list_name.get(entry.get("ListID"), "")
    if list_name:
        record.sanctions_lists.append(list_name)

    for event in children(entry, "EntryEvent"):
        rendered = format_ymd(first_child(event, "Date"))
        if rendered:
            record.listed_on.append(rendered)

    for measure in children(entry, "SanctionsMeasure"):
        if ref.sanctions_type.get(measure.get("SanctionsTypeID")) == "Program":
            program = child_text(measure, "Comment")
            if program:
                record.programs.append(program)

    record.listed_on.sort()
    if record.listed_on:
        record.listed_on = [record.listed_on[0]]
