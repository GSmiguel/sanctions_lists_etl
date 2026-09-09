"""Stream the SDN advanced XML into flat :class:`PartyRecord` rows.

The file is laid out as: ``ReferenceValueSets`` -> ``Locations`` ->
``IDRegDocuments`` -> ``DistinctParties`` -> ``SanctionsEntries``.  Locations and
ID documents are needed while reading a party; sanctions entries come afterwards
and are joined back onto the already-built records by profile id.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable
from xml.etree.ElementTree import Element, iterparse

from .references import ReferenceData, localname, parse_reference_data

LATIN_SCRIPT_ID = "215"

# Feature type ids with dedicated columns (stable in the OFAC schema).
FEATURE_BIRTHDATE = "8"
FEATURE_BIRTHPLACE = "9"
FEATURE_NATIONALITY = "10"
FEATURE_CITIZENSHIP = "11"
FEATURE_WEBSITE = "14"
FEATURE_EMAIL = "21"
FEATURE_TITLE = "26"
FEATURE_GENDER = "224"

# Column order for the flat sheet.
COLUMNS: list[tuple[str, str]] = [
    ("fixed_ref", "id_ofac"),
    ("party_type", "tipo"),
    ("primary_name", "nome_principal"),
    ("aliases", "nomes_alternativos"),
    ("birth_dates", "data_nascimento"),
    ("birth_places", "local_nascimento"),
    ("nationalities", "nacionalidades"),
    ("citizenships", "cidadanias"),
    ("genders", "genero"),
    ("titles", "titulos"),
    ("address_countries", "paises"),
    ("addresses", "enderecos"),
    ("documents", "documentos"),
    ("programs", "programas"),
    ("sanctions_lists", "listas"),
    ("listed_on", "data_listagem"),
    ("emails", "emails"),
    ("websites", "websites"),
    ("crypto_addresses", "enderecos_cripto"),
    ("other_features", "outras_caracteristicas"),
]

_LIST_SEP = "; "


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

    for _, elem in iterparse(str(source), events=("end",)):
        tag = localname(elem.tag)

        if tag == "ReferenceValueSets":
            ref = parse_reference_data(elem)
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
        elif tag == "SanctionsEntry":
            assert ref is not None
            _attach_sanctions_entry(elem, ref, records)
            elem.clear()

    return list(records.values())


def rows_from_records(records: list[PartyRecord]) -> list[dict[str, str]]:
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
    profile = _find(party, "Profile")
    if profile is None:
        return None

    record = PartyRecord(fixed_ref=party.get("FixedRef", ""))
    record.party_type = ref.party_type_for_subtype(profile.get("PartySubTypeID"))

    identity = _find(profile, "Identity")
    if identity is not None:
        primary, aliases = _resolve_names(identity, ref)
        record.primary_name = primary
        record.aliases = aliases
        identity_id = identity.get("ID")
        if identity_id in docs_by_identity:
            record.documents = docs_by_identity.pop(identity_id)

    for feature in _findall(profile, "Feature"):
        _apply_feature(feature, ref, record, locations, location_countries)

    return record


def _resolve_names(identity: Element, ref: ReferenceData) -> tuple[str, list[str]]:
    group_type: dict[str, str] = {}
    groups = _find(identity, "NamePartGroups")
    if groups is not None:
        for master in _findall(groups, "MasterNamePartGroup"):
            npg = _find(master, "NamePartGroup")
            if npg is not None:
                group_type[npg.get("ID")] = ref.name_part_type.get(
                    npg.get("NamePartTypeID"), ""
                )

    primary = ""
    aliases: list[str] = []
    for alias in _findall(identity, "Alias"):
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
    documented = _findall(alias, "DocumentedName")
    # Prefer the base ("status 1") rendering, then any others (scripts, variants).
    documented.sort(key=lambda d: (d.get("DocNameStatusID") != "1",))
    rendered: list[str] = []
    for doc in documented:
        parts: list[tuple[str, str]] = []
        for part in _findall(doc, "DocumentedNamePart"):
            value = _find(part, "NamePartValue")
            if value is None or not (value.text or "").strip():
                continue
            group_id = value.get("NamePartGroupID")
            parts.append((group_type.get(group_id, ""), value.text.strip()))
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
    for version in _findall(feature, "FeatureVersion"):
        values.extend(_feature_version_values(version, ref, locations))
        for version_location in _findall(version, "VersionLocation"):
            loc_id = version_location.get("LocationID")
            if loc_id in location_countries:
                record.address_countries.append(location_countries[loc_id])

    if not values:
        return

    if type_id == FEATURE_BIRTHDATE:
        record.birth_dates.extend(values)
    elif type_id == FEATURE_BIRTHPLACE:
        record.birth_places.extend(values)
    elif type_id == FEATURE_NATIONALITY:
        record.nationalities.extend(values)
    elif type_id == FEATURE_CITIZENSHIP:
        record.citizenships.extend(values)
    elif type_id == FEATURE_GENDER:
        record.genders.extend(values)
    elif type_id == FEATURE_TITLE:
        record.titles.extend(values)
    elif type_id == FEATURE_EMAIL:
        record.emails.extend(values)
    elif type_id == FEATURE_WEBSITE:
        record.websites.extend(values)
    elif type_name.startswith("Digital Currency Address"):
        currency = type_name.split("-")[-1].strip()
        record.crypto_addresses.extend(f"{currency}: {value}" for value in values)
    elif type_name == "Location" or type_id == "25":
        record.addresses.extend(values)
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
            loc_id = child.get("LocationID")
            if loc_id in locations:
                values.append(locations[loc_id])
        elif name == "DatePeriod":
            rendered = _format_date_period(child)
            if rendered:
                values.append(rendered)
        elif name == "VersionDetail":
            text = (child.text or "").strip()
            if text:
                values.append(text)
            else:
                ref_id = child.get("DetailReferenceID")
                if ref_id and ref_id in ref.detail_reference:
                    values.append(ref.detail_reference[ref_id])
    return values


# --------------------------------------------------------------------------- #
# locations & documents
# --------------------------------------------------------------------------- #
def _format_location(location: Element, ref: ReferenceData) -> tuple[str, str]:
    ordered: dict[str, str] = {}
    for part in _findall(location, "LocationPart"):
        kind = ref.loc_part_type.get(part.get("LocPartTypeID"), part.get("LocPartTypeID", ""))
        value_el = _find(part, "LocationPartValue")
        value = ""
        if value_el is not None:
            inner = _find(value_el, "Value")
            value = (inner.text or "").strip() if inner is not None else ""
        if value:
            ordered.setdefault(kind, value)

    country_el = _find(location, "LocationCountry")
    country = ""
    if country_el is not None:
        country = ref.country.get(country_el.get("CountryID"), "")
    if not country:
        area_el = _find(location, "LocationAreaCode")
        if area_el is not None:
            country = ref.area_code_country.get(area_el.get("AreaCodeID"), "")
    if country.lower() in {"undetermined", "unknown"}:
        country = ""

    sequence = ["ADDRESS1", "ADDRESS2", "ADDRESS3", "REGION", "CITY", "STATE/PROVINCE", "POSTAL CODE"]
    pieces = [ordered[key] for key in sequence if key in ordered]
    pieces.extend(value for key, value in ordered.items() if key not in sequence)
    if country:
        pieces.append(country)
    return ", ".join(pieces), country


def _format_document(document: Element, ref: ReferenceData) -> str:
    doc_type = ref.id_reg_doc_type.get(document.get("IDRegDocTypeID"), "ID")
    number_el = _find(document, "IDRegistrationNo")
    number = (number_el.text or "").strip() if number_el is not None else ""
    if not number:
        return ""
    rendered = f"{doc_type}: {number}"
    country = ref.country.get(document.get("IssuedBy-CountryID"), "")
    if country:
        rendered += f" ({country})"
    authority_el = _find(document, "IssuingAuthority")
    authority = (authority_el.text or "").strip() if authority_el is not None else ""
    if authority:
        rendered += f" - {authority}"
    return rendered


# --------------------------------------------------------------------------- #
# sanctions entries
# --------------------------------------------------------------------------- #
def _attach_sanctions_entry(
    entry: Element, ref: ReferenceData, records: dict[str, PartyRecord]
) -> None:
    profile_id = entry.get("ProfileID")
    record = records.get(profile_id)
    if record is None:
        return

    list_name = ref.list_name.get(entry.get("ListID"), "")
    if list_name:
        record.sanctions_lists.append(list_name)

    for event in _findall(entry, "EntryEvent"):
        date_el = _find(event, "Date")
        rendered = _format_ymd(date_el) if date_el is not None else ""
        if rendered:
            record.listed_on.append(rendered)

    for measure in _findall(entry, "SanctionsMeasure"):
        type_name = ref.sanctions_type.get(measure.get("SanctionsTypeID"), "")
        comment_el = _find(measure, "Comment")
        comment = (comment_el.text or "").strip() if comment_el is not None else ""
        if type_name == "Program" and comment:
            record.programs.append(comment)

    record.listed_on.sort()
    if record.listed_on:
        record.listed_on = [record.listed_on[0]]


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def _find(parent: Element, name: str) -> Element | None:
    for child in parent:
        if localname(child.tag) == name:
            return child
    return None


def _findall(parent: Element, name: str) -> list[Element]:
    return [child for child in parent if localname(child.tag) == name]


def _format_date_period(period: Element) -> str:
    start = _find(period, "Start")
    end = _find(period, "End")
    first = _format_ymd(_find(start, "From")) if start is not None else ""
    last = _format_ymd(_find(end, "To")) if end is not None else ""
    if first and last and first != last:
        return f"{first} to {last}"
    return first or last


def _format_ymd(node: Element | None) -> str:
    if node is None:
        return ""
    year = _child_text(node, "Year")
    month = _child_text(node, "Month")
    day = _child_text(node, "Day")
    if not year:
        return ""
    out = year
    if month:
        out += f"-{int(month):02d}"
        if day:
            out += f"-{int(day):02d}"
    return out


def _child_text(node: Element, name: str) -> str:
    child = _find(node, name)
    return (child.text or "").strip() if child is not None else ""
