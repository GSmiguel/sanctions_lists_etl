"""The single unified BigQuery table's field list.

Pure Python — no ``google-cloud-bigquery`` import — so it stays usable (and
testable) without the optional ``bigquery`` extra installed.
:mod:`sanctions_lists_etl.common.sinks.bigquery` turns this into real
``bigquery.SchemaField`` objects and DDL at the point it actually talks to
BigQuery.

One row per currently-listed party (``uid``) — ``entries`` holds only current
state, kept that way via a per-source ``MERGE`` (upsert + delete-if-absent),
not a full copy appended every day. See
``sanctions_lists_etl.common.sinks.bigquery`` for the merge strategy and
:data:`SINK_MANAGED_FIELDS` for how ``first_seen_date``/``last_seen_date``
give a lightweight audit trail without the storage cost of a daily snapshot.
"""

from __future__ import annotations

# (name, type, mode) in BigQuery's own vocabulary — this is the row shape
# every source's ``to_normalized()`` must produce (see test_normalize_contract.py).
ENTRIES_FIELDS: list[tuple[str, str, str]] = [
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

# Columns that live on ``entries`` but are managed by BigQuerySink's MERGE
# itself, not by any source's to_normalized() — set on INSERT, first_seen_date
# left untouched and last_seen_date refreshed on every UPDATE. Kept separate
# from ENTRIES_FIELDS so the normalize-contract tests don't expect sources to
# fill them.
SINK_MANAGED_FIELDS: list[tuple[str, str, str]] = [
    ("first_seen_date", "DATE", "REQUIRED"),
    ("last_seen_date", "DATE", "REQUIRED"),
]

FIELD_NAMES: frozenset[str] = frozenset(name for name, _, _ in ENTRIES_FIELDS)
REQUIRED_FIELDS: frozenset[str] = frozenset(
    name for name, _, mode in ENTRIES_FIELDS if mode == "REQUIRED"
)

# The `source` value each source's to_normalized() uses — also the table's
# CLUSTER BY key and the per-source scope of the MERGE's delete branch.
SOURCE_KEYS: tuple[str, ...] = ("ofac_sdn", "ofac_consolidated", "eu_fsf", "un_sc", "uk_fcdo")

DATASET_NAME = "sanctions"
ENTRIES_TABLE = "entries"
STAGING_TABLE = "entries_staging"
MANIFEST_TABLE = "snapshot_manifest"
CURRENT_VIEW = "entries_current"
