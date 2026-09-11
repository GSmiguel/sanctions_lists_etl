"""Map a :class:`~.parser.SanctionParty` onto the unified BigQuery row shape.

See :mod:`sanctions_lists_etl.common.schema` for the field list this must stay
inside of; :mod:`sanctions_lists_etl.tests.test_normalize_contract` pins that.
"""

from __future__ import annotations

from ...common.records import as_array
from .parser import SanctionParty

SOURCE_AUTHORITY = "UK"


def to_normalized(
    record: SanctionParty,
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
        "source_reference": record.uk_unique_id,
        "uid": f"{source_key}:{record.uk_unique_id}",
        "party_type": record.party_type,
        "primary_name": record.primary_name,
        "name_original_script": record.name_original_script,
        "un_reference": record.un_reference_number,
        "aliases": as_array(record.aliases),
        "birth_dates": as_array(record.birth_dates),
        "birth_places": as_array(record.birth_places),
        "nationalities": as_array(record.nationalities),
        "citizenships": [],
        "genders": as_array(record.genders),
        "titles": as_array(record.titles),
        "functions": as_array(record.positions),
        "address_countries": as_array(record.address_countries),
        "addresses": as_array(record.addresses),
        "documents": as_array(record.documents),
        "programs": as_array(record.regime_name),
        "sanctions_lists": [],
        "listed_on": as_array(record.listed_on),
        "last_updated": as_array(record.last_updated),
        "emails": as_array(record.emails),
        "phones": as_array(record.phones),
        "websites": as_array(record.websites),
        "crypto_addresses": [],
        "remarks": record.other_information,
        "source_fields": {
            "ofsi_group_id": record.ofsi_group_id,
            "designation_source": record.designation_source,
            "sanctions_imposed": as_array(record.sanctions_imposed),
            "entity_type": as_array(record.entity_type),
            "parent_companies": as_array(record.parent_companies),
            "subsidiaries": as_array(record.subsidiaries),
            "vessel_info": record.vessel_info,
            "statement_of_reasons": record.statement_of_reasons,
        },
        "source_sha256": source_sha256,
        "ingested_at": ingested_at,
    }
