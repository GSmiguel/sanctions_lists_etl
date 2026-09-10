"""Flatten an INTERPOL notices snapshot (JSON) into :class:`Notice` rows.

The snapshot written by :mod:`.download` is a JSON array of notice objects, each
the notice's summary merged with its full record and tagged with a private
``_notice_kind`` field (``"red"``, ``"un-person"`` or ``"un-entity"``).  Unlike
the other sources this is not XML and there are no reference tables — every value
is already inline — so parsing is a plain dict walk.  Country, eye/hair and a
few language codes are expanded via :mod:`sanctions_lists_etl.common.countries`
and the small maps below; anything unrecognised passes through untouched.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

log = logging.getLogger(__name__)

from ...common.countries import country_name
from .columns import COLUMNS

_LIST_SEP = "; "
_PART_SEP = ", "

_NOTICE_TYPE = {
    "red": "Red Notice",
    "un-person": "UN Special Notice",
    "un-entity": "UN Special Notice",
}
_ENTITY_KINDS = {"un-entity"}
# _notice_kind -> the "red" / "un" family used by the --red-only / --un-only filter.
_FAMILY = {"red": "red", "un-person": "un", "un-entity": "un"}

_SEX = {"M": "Male", "F": "Female", "U": "Unknown"}

_EYE_COLOURS = {
    "BLA": "black", "BLU": "blue", "BRO": "brown", "BROH": "brown",
    "GRE": "green", "GRA": "grey", "GRY": "grey", "HAZ": "hazel",
    "MAR": "maroon", "MUL": "multicoloured", "PIN": "pink", "UNK": "unknown",
}
_HAIR_COLOURS = {
    "BAL": "bald", "BLD": "blonde", "BLN": "blonde", "BLA": "black",
    "BRO": "brown", "BROH": "brown", "GRY": "grey", "GRA": "grey",
    "RED": "red", "WHI": "white", "SAN": "sandy", "OTH": "other", "OTHD": "other",
    "UNK": "unknown",
}
_LANGUAGES = {
    "ARA": "Arabic", "CHE": "Chechen", "CHI": "Chinese", "DUT": "Dutch",
    "ENG": "English", "FRE": "French", "GER": "German", "GRE": "Greek",
    "HEB": "Hebrew", "HIN": "Hindi", "ITA": "Italian", "JPN": "Japanese",
    "KOR": "Korean", "PER": "Persian", "POL": "Polish", "POR": "Portuguese",
    "RUS": "Russian", "SPA": "Spanish", "TUR": "Turkish", "UKR": "Ukrainian",
    "URD": "Urdu",
}


@dataclass
class Notice:
    interpol_notice_id: str
    notice_type: str = ""
    un_reference: str = ""
    party_type: str = "Individual"
    primary_name: str = ""
    aliases: list[str] = field(default_factory=list)
    birth_dates: list[str] = field(default_factory=list)
    birth_places: list[str] = field(default_factory=list)
    nationalities: list[str] = field(default_factory=list)
    genders: list[str] = field(default_factory=list)
    charges: list[str] = field(default_factory=list)
    warrant_countries: list[str] = field(default_factory=list)
    documents: list[str] = field(default_factory=list)
    languages_spoken: list[str] = field(default_factory=list)
    physical_description: list[str] = field(default_factory=list)
    listed_on: list[str] = field(default_factory=list)
    notice_url: str = ""
    image_url: str = ""
    summary: str = ""

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


def parse_interpol(
    source: Path | str,
    *,
    notice_types: Iterable[str] | None = None,
) -> list[Notice]:
    """Parse ``source`` and return one :class:`Notice` per record.

    ``notice_types`` optionally restricts the output to the ``"red"`` and/or
    ``"un"`` families (case-insensitive).
    """
    keep = {t.lower() for t in notice_types} if notice_types is not None else None

    raw = json.loads(Path(source).read_text(encoding="utf-8"))
    records: list[Notice] = []
    for obj in raw:
        kind = obj.get("_notice_kind", "red")
        if keep is not None and _FAMILY.get(kind, "red") not in keep:
            continue
        records.append(_build_notice(obj, kind))

    log.info("parsed %d notices", len(records))
    return records


def rows_from_records(records: Iterable[Notice]) -> list[dict[str, str]]:
    return [record.to_row() for record in records]


# --------------------------------------------------------------------------- #
# notice assembly
# --------------------------------------------------------------------------- #
def _build_notice(obj: dict[str, Any], kind: str) -> Notice:
    record = Notice(
        interpol_notice_id=str(obj.get("entity_id") or "").strip(),
        notice_type=_NOTICE_TYPE.get(kind, "Red Notice"),
        un_reference=str(obj.get("un_reference") or "").strip(),
        party_type="Entity" if kind in _ENTITY_KINDS else "Individual",
        primary_name=_person_name(obj.get("name"), obj.get("forename")),
    )

    original = _person_name(
        obj.get("name_in_original_script"), obj.get("forename_in_original_script")
    )
    if original:
        record.aliases.append(original)
    for alias in obj.get("aliases") or []:
        rendered = _person_name(alias.get("name"), alias.get("forename"))
        born = _iso_date(alias.get("date_of_birth"))
        if born:
            rendered = f"{rendered} (b. {born})" if rendered else rendered
        if rendered:
            record.aliases.append(rendered)
    for label, value in (
        ("name at birth", obj.get("name_at_birth")),
        ("mother", _person_name(obj.get("mother_name"), obj.get("mother_forename"))),
        ("father", _person_name(None, obj.get("father_forename"))),
    ):
        text = (value or "").strip()
        if text:
            record.aliases.append(f"{text} ({label})")

    born = _iso_date(obj.get("date_of_birth"))
    if born:
        record.birth_dates.append(born)
    place = _join(obj.get("place_of_birth"), country_name(obj.get("country_of_birth_id")))
    if place:
        record.birth_places.append(place)

    record.nationalities = [country_name(c) for c in obj.get("nationalities") or [] if c]

    gender = _SEX.get(str(obj.get("sex_id") or "").upper())
    if gender:
        record.genders.append(gender)

    for warrant in obj.get("arrest_warrants") or []:
        charge = _charge(warrant.get("charge"))
        translation = _charge(warrant.get("charge_translation"))
        if translation and translation != charge:
            charge = f"{charge} [EN: {translation}]" if charge else translation
        if charge:
            record.charges.append(charge)
        country = country_name(warrant.get("issuing_country_id"))
        if country:
            record.warrant_countries.append(country)

    for document in obj.get("identity_documents") or []:
        rendered = _format_document(document)
        if rendered:
            record.documents.append(rendered)

    record.languages_spoken = [
        _LANGUAGES.get(str(code).upper(), str(code).upper())
        for code in obj.get("languages_spoken_ids") or []
        if code
    ]

    record.physical_description = _physical_description(obj)

    profession = (obj.get("profession") or "").strip()
    summary = _clean(obj.get("summary"))
    if profession and not summary:
        summary = f"Profession: {profession}"
    elif profession:
        summary = f"Profession: {profession}. {summary}"
    record.summary = summary

    links = obj.get("_links") or {}
    record.notice_url = _href(links.get("self"))
    record.image_url = _href(links.get("thumbnail")) or _href(links.get("images"))

    return record


def _person_name(name: Any, forename: Any) -> str:
    """Render a name surname-first (``SURNAME, Forename``), matching the OFAC export."""
    surname = (name or "").strip()
    given = (forename or "").strip()
    if surname and given:
        return f"{surname}, {given}"
    return surname or given


def _iso_date(value: Any) -> str:
    """``"1993/02/15"`` -> ``"1993-02-15"``; zero month/day are dropped."""
    text = (value or "").strip()
    if not text:
        return ""
    parts = text.replace("-", "/").split("/")
    if not parts or not parts[0].isdigit() or parts[0] in ("0", "0000"):
        return ""
    out = parts[0].zfill(4)
    for part in parts[1:]:
        if part.isdigit() and int(part) > 0:
            out += f"-{int(part):02d}"
        else:
            break
    return out


def _format_document(document: dict[str, Any]) -> str:
    kind = (document.get("type") or "ID").strip()
    number = (document.get("nr") or "").strip()
    if not number:
        return ""
    rendered = f"{kind}: {number}"
    country = country_name(document.get("issuing_country_id") or document.get("citizenship_id"))
    if country:
        rendered += f" ({country})"
    issued = (document.get("issued_on") or "").strip()
    if issued:
        rendered += f" [issued {_iso_date(issued) or issued}]"
    expiry = (document.get("expiry_date") or "").strip()
    if expiry:
        rendered += f" [expires {_iso_date(expiry) or expiry}]"
    place = (document.get("place_of_issue") or "").strip()
    if place:
        rendered += f" ({place})"
    return rendered


def _physical_description(obj: dict[str, Any]) -> list[str]:
    out: list[str] = []
    height = obj.get("height")
    if isinstance(height, (int, float)) and height > 0:
        out.append(f"{height:g} m")
    weight = obj.get("weight")
    if isinstance(weight, (int, float)) and weight > 0:
        out.append(f"{weight:g} kg")
    eyes = _codes(obj.get("eyes_colors_id"), _EYE_COLOURS)
    if eyes:
        out.append(f"eyes: {eyes}")
    hair = _codes(obj.get("hairs_id"), _HAIR_COLOURS)
    if hair:
        out.append(f"hair: {hair}")
    marks = _clean(obj.get("distinguishing_marks"))
    if marks:
        out.append(marks)
    return out


def _codes(values: Any, table: dict[str, str]) -> str:
    if not values:
        return ""
    return _PART_SEP.join(
        table.get(str(v).upper(), str(v).upper()) for v in values if v
    )


def _href(link: Any) -> str:
    if isinstance(link, dict):
        return (link.get("href") or "").strip()
    return ""


def _join(*parts: Any) -> str:
    pieces: list[str] = []
    for part in parts:
        text = (part or "").strip()
        if text and text not in pieces:
            pieces.append(text)
    return _PART_SEP.join(pieces)


def _clean(value: Any) -> str:
    return " ".join((value or "").split())


def _charge(value: Any) -> str:
    """Tidy an arrest-warrant charge: collapse whitespace, drop leading bullets,
    turn the feed's ``- foo - bar`` run-ons into ``foo; bar``."""
    text = _clean(value).lstrip("-•*  ").strip()
    text = text.replace(" - ", "; ")
    return text.strip(" ;,")
