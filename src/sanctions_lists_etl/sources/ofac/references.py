"""Parse the ``<ReferenceValueSets>`` block of the SDN advanced XML.

Every coded attribute in the file (alias type, feature type, country, document
type, ...) points into one of these lookup tables, so they must be read before
the party records are processed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from xml.etree.ElementTree import Element

from ...common.xmlutils import localname

NAMESPACE = (
    "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/ADVANCED_XML"
)


@dataclass
class ReferenceData:
    party_type: dict[str, str] = field(default_factory=dict)
    party_subtype_to_type: dict[str, str] = field(default_factory=dict)
    alias_type: dict[str, str] = field(default_factory=dict)
    name_part_type: dict[str, str] = field(default_factory=dict)
    feature_type: dict[str, str] = field(default_factory=dict)
    country: dict[str, str] = field(default_factory=dict)
    area_code_country: dict[str, str] = field(default_factory=dict)
    loc_part_type: dict[str, str] = field(default_factory=dict)
    id_reg_doc_type: dict[str, str] = field(default_factory=dict)
    detail_reference: dict[str, str] = field(default_factory=dict)
    sanctions_type: dict[str, str] = field(default_factory=dict)
    list_name: dict[str, str] = field(default_factory=dict)

    def party_type_for_subtype(self, subtype_id: str | None) -> str:
        return self.party_subtype_to_type.get(subtype_id or "", "Unknown")


def parse_reference_data(element: Element) -> ReferenceData:
    """Build a :class:`ReferenceData` from a ``<ReferenceValueSets>`` element."""
    ref = ReferenceData()
    subtype_raw: dict[str, tuple[str | None, str]] = {}

    for group in element:
        name = localname(group.tag)
        if name == "PartyTypeValues":
            for item in group:
                ref.party_type[item.get("ID")] = _text(item)
        elif name == "PartySubTypeValues":
            for item in group:
                subtype_raw[item.get("ID")] = (item.get("PartyTypeID"), _text(item))
        elif name == "AliasTypeValues":
            for item in group:
                ref.alias_type[item.get("ID")] = _text(item)
        elif name == "NamePartTypeValues":
            for item in group:
                ref.name_part_type[item.get("ID")] = _text(item)
        elif name == "FeatureTypeValues":
            for item in group:
                ref.feature_type[item.get("ID")] = _text(item)
        elif name == "CountryValues":
            for item in group:
                ref.country[item.get("ID")] = _text(item)
        elif name == "AreaCodeValues":
            for item in group:
                ref.area_code_country[item.get("ID")] = item.get("Description") or _text(item)
        elif name == "LocPartTypeValues":
            for item in group:
                ref.loc_part_type[item.get("ID")] = _text(item)
        elif name == "IDRegDocTypeValues":
            for item in group:
                ref.id_reg_doc_type[item.get("ID")] = _text(item)
        elif name == "DetailReferenceValues":
            for item in group:
                ref.detail_reference[item.get("ID")] = _text(item)
        elif name == "SanctionsTypeValues":
            for item in group:
                ref.sanctions_type[item.get("ID")] = _text(item)
        elif name == "ListValues":
            for item in group:
                ref.list_name[item.get("ID")] = _text(item)

    for subtype_id, (party_type_id, subtype_text) in subtype_raw.items():
        # PartySubType text distinguishes Vessel/Aircraft; for people and
        # organisations it is just "Unknown", so fall back to the PartyType.
        if subtype_text and subtype_text != "Unknown":
            ref.party_subtype_to_type[subtype_id] = subtype_text
        else:
            ref.party_subtype_to_type[subtype_id] = ref.party_type.get(
                party_type_id, "Unknown"
            )

    return ref


def _text(element: Element) -> str:
    return (element.text or "").strip()
