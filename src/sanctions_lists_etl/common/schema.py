"""The single unified BigQuery table's field list.

Pure Python — no ``google-cloud-bigquery`` import — so it stays usable (and
testable) without the optional ``bigquery`` extra installed.
:mod:`sanctions_lists_etl.common.sinks.bigquery` turns this into real
``bigquery.SchemaField`` objects and DDL at the point it actually talks to
BigQuery.

One row per sanctioned party per source per day it was (re)fetched — see
``sanctions_lists_etl.common.sinks.bigquery`` for the load strategy (dated
snapshots, not row-level diffing) and the project memory
``bigquery-target-and-unified-schema`` for the full rationale.
"""

from __future__ import annotations

# (name, type, mode) in BigQuery's own vocabulary.
ENTRIES_FIELDS: list[tuple[str, str, str]] = [
    ("snapshot_date", "DATE", "REQUIRED"),
    ("source", "STRING", "REQUIRED"),
    ("source_authority", "STRING", "REQUIRED"),
    ("source_reference", "STRING", "REQUIRED"),
    ("uid", "STRING", "REQUIRED"),
    ("party_type", "STRING", "REQUIRED"),
    ("primary_name", "STRING", "REQUIRED"),
    ("name_original_script", "STRING", "NULLABLE"),
    ("un_reference", "STRING", "NULLABLE"),
    ("aliases", "STRING", "REPEATED"),
    ("birth_dates", "STRING", "REPEATED"),
    ("birth_places", "STRING", "REPEATED"),
    ("nationalities", "STRING", "REPEATED"),
    ("citizenships", "STRING", "REPEATED"),
    ("genders", "STRING", "REPEATED"),
    ("titles", "STRING", "REPEATED"),
    ("functions", "STRING", "REPEATED"),
    ("address_countries", "STRING", "REPEATED"),
    ("addresses", "STRING", "REPEATED"),
    ("documents", "STRING", "REPEATED"),
    ("programs", "STRING", "REPEATED"),
    ("sanctions_lists", "STRING", "REPEATED"),
    ("listed_on", "STRING", "REPEATED"),
    ("last_updated", "STRING", "REPEATED"),
    ("emails", "STRING", "REPEATED"),
    ("phones", "STRING", "REPEATED"),
    ("websites", "STRING", "REPEATED"),
    ("crypto_addresses", "STRING", "REPEATED"),
    ("remarks", "STRING", "NULLABLE"),
    ("source_fields", "JSON", "NULLABLE"),
    ("source_sha256", "STRING", "NULLABLE"),
    ("ingested_at", "TIMESTAMP", "REQUIRED"),
]

FIELD_NAMES: frozenset[str] = frozenset(name for name, _, _ in ENTRIES_FIELDS)
REQUIRED_FIELDS: frozenset[str] = frozenset(
    name for name, _, mode in ENTRIES_FIELDS if mode == "REQUIRED"
)

# The `source` value each source's to_normalized() uses — also the table's
# CLUSTER BY / partition-scoped-delete key. OFAC fans out into two.
SOURCE_KEYS: tuple[str, ...] = ("ofac_sdn", "ofac_consolidated", "eu_fsf", "un_sc", "uk_fcdo")

DATASET_NAME = "sanctions"
ENTRIES_TABLE = "entries"
MANIFEST_TABLE = "snapshot_manifest"
CURRENT_VIEW = "entries_current"
