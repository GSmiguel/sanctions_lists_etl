"""Map a :class:`~.parser.SanctionEntity` onto the unified BigQuery row shape.

See :mod:`sanctions_lists_etl.common.schema` for the field list this must stay
inside of; :mod:`sanctions_lists_etl.tests.test_normalize_contract` pins that.
"""

from __future__ import annotations

from ...common.records import as_array
from .parser import SanctionEntity

SOURCE_AUTHORITY = "EU"


def to_normalized(
    record: SanctionEntity,
    *,
    source_key: str,
    snapshot_date: str,
    source_sha256: str,
    ingested_at: str,
) -> dict:
    return {
        "snapshot_date": snapshot_date,
        "source": source_key,
        "source_authority": SOURCE_AUTHORITY,
        "source_reference": record.eu_reference_number,
        "uid": f"{source_key}:{record.eu_reference_number}",
        "party_type": record.party_type,
        "primary_name": record.primary_name,
        "name_original_script": "",
        "un_reference": record.un_id,
        "aliases": as_array(record.aliases),
        "birth_dates": as_array(record.birth_dates),
        "birth_places": as_array(record.birth_places),
        "nationalities": [],
        "citizenships": as_array(record.citizenships),
        "genders": as_array(record.genders),
        "titles": as_array(record.titles),
        "functions": as_array(record.functions),
        "address_countries": as_array(record.address_countries),
        "addresses": as_array(record.addresses),
        "documents": as_array(record.documents),
        "programs": as_array(record.programmes),
        "sanctions_lists": [],
        "listed_on": as_array(record.listed_on),
        "last_updated": [],
        "emails": as_array(record.emails),
        "phones": as_array(record.phones),
        "websites": as_array(record.websites),
        "crypto_addresses": [],
        "remarks": "; ".join(as_array(record.remarks)),
        "source_fields": {
            "regulations": as_array(record.regulations),
            "subject_code": record.subject_code,
        },
        "source_sha256": source_sha256,
        "ingested_at": ingested_at,
    }
