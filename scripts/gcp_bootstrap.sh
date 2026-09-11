#!/usr/bin/env bash
# Provisions everything P1 needs in the GCP project: the BigQuery dataset/
# tables/view, the loader service account, and Workload Identity Federation so
# GitHub Actions can authenticate without a long-lived key.
#
# Idempotent — safe to re-run. Requires `gcloud`/`bq` authenticated
# (`gcloud auth login --update-adc`) against an account with owner/editor on
# the project, and a billing account linked (BigQuery's zero-billing "sandbox"
# mode blocks DML — DELETE/MERGE — entirely, not just the 60-day table
# expiry, so the loader in common/sinks/bigquery.py needs billing linked to
# run at all: `gcloud billing projects link <PROJECT> --billing-account=<ID>`).
#
# The table/view DDL here must be kept in sync by hand with
# src/sanctions_lists_etl/common/schema.py::ENTRIES_FIELDS — there is no
# codegen step. Run from the repo root:
#
#   PROJECT_ID=sanctions-screening-508311 ./scripts/gcp_bootstrap.sh

set -euo pipefail

PROJECT_ID="${PROJECT_ID:?set PROJECT_ID, e.g. PROJECT_ID=sanctions-screening-508311}"
DATASET="${DATASET:-sanctions}"
LOCATION="${LOCATION:-US}"
SERVICE_ACCOUNT="${SERVICE_ACCOUNT:-sanctions-etl-loader}"
SA_EMAIL="${SERVICE_ACCOUNT}@${PROJECT_ID}.iam.gserviceaccount.com"
WIF_POOL="${WIF_POOL:-github-actions-pool}"
WIF_PROVIDER="${WIF_PROVIDER:-github-actions-provider}"
GITHUB_REPO="${GITHUB_REPO:-GSmiguel/sanctions_lists_etl}"

echo "== enabling APIs =="
gcloud services enable \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  sts.googleapis.com \
  cloudresourcemanager.googleapis.com \
  bigquery.googleapis.com \
  --project="${PROJECT_ID}"

echo "== dataset =="
bq --project_id="${PROJECT_ID}" mk --dataset \
  --location="${LOCATION}" \
  --description="Unified public sanctions lists (OFAC/EU/UN/UK)" \
  "${DATASET}" 2>&1 | grep -qv "already exists" || true

echo "== entries table (partitioned by snapshot_date, clustered by source/party_type/primary_name) =="
bq query --project_id="${PROJECT_ID}" --use_legacy_sql=false <<SQL
CREATE TABLE IF NOT EXISTS \`${PROJECT_ID}.${DATASET}.entries\` (
  snapshot_date DATE NOT NULL,
  source STRING NOT NULL,
  source_authority STRING NOT NULL,
  source_reference STRING NOT NULL,
  uid STRING NOT NULL,
  party_type STRING NOT NULL,
  primary_name STRING NOT NULL,
  name_original_script STRING,
  un_reference STRING,
  aliases ARRAY<STRING>,
  birth_dates ARRAY<STRING>,
  birth_places ARRAY<STRING>,
  nationalities ARRAY<STRING>,
  citizenships ARRAY<STRING>,
  genders ARRAY<STRING>,
  titles ARRAY<STRING>,
  functions ARRAY<STRING>,
  address_countries ARRAY<STRING>,
  addresses ARRAY<STRING>,
  documents ARRAY<STRING>,
  programs ARRAY<STRING>,
  sanctions_lists ARRAY<STRING>,
  listed_on ARRAY<STRING>,
  last_updated ARRAY<STRING>,
  emails ARRAY<STRING>,
  phones ARRAY<STRING>,
  websites ARRAY<STRING>,
  crypto_addresses ARRAY<STRING>,
  remarks STRING,
  source_fields JSON,
  source_sha256 STRING,
  ingested_at TIMESTAMP NOT NULL
)
PARTITION BY snapshot_date
CLUSTER BY source, party_type, primary_name
OPTIONS (
  description = "One row per sanctioned party per source per day it was (re)fetched. See common/schema.py."
);
SQL

echo "== snapshot_manifest table + entries_current view =="
bq query --project_id="${PROJECT_ID}" --use_legacy_sql=false <<SQL
CREATE TABLE IF NOT EXISTS \`${PROJECT_ID}.${DATASET}.snapshot_manifest\` (
  source STRING NOT NULL,
  latest_snapshot_date DATE NOT NULL
)
OPTIONS (
  description = "Latest snapshot_date loaded per source; entries_current joins on this."
);

CREATE OR REPLACE VIEW \`${PROJECT_ID}.${DATASET}.entries_current\` AS
SELECT e.*
FROM \`${PROJECT_ID}.${DATASET}.entries\` e
JOIN \`${PROJECT_ID}.${DATASET}.snapshot_manifest\` m
  ON e.source = m.source AND e.snapshot_date = m.latest_snapshot_date;
SQL

echo "== loader service account =="
gcloud iam service-accounts describe "${SA_EMAIL}" --project="${PROJECT_ID}" >/dev/null 2>&1 || \
  gcloud iam service-accounts create "${SERVICE_ACCOUNT}" \
    --project="${PROJECT_ID}" \
    --display-name="sanctions-etl BigQuery loader (GitHub Actions)"

# Dataset-scoped `bq add-iam-policy-binding` is allowlist-only as of this
# writing ("This feature requires allowlisting"), so this grants at the
# project level instead — broader than "just this dataset", acceptable for a
# single-purpose project.
echo "== IAM roles (project-scoped: dataset-level binding needs allowlisting) =="
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/bigquery.dataEditor" \
  --condition=None >/dev/null
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/bigquery.jobUser" \
  --condition=None >/dev/null

echo "== Workload Identity Pool + GitHub OIDC provider =="
gcloud iam workload-identity-pools describe "${WIF_POOL}" \
  --project="${PROJECT_ID}" --location=global >/dev/null 2>&1 || \
  gcloud iam workload-identity-pools create "${WIF_POOL}" \
    --project="${PROJECT_ID}" --location=global \
    --display-name="GitHub Actions"

gcloud iam workload-identity-pools providers describe "${WIF_PROVIDER}" \
  --project="${PROJECT_ID}" --location=global --workload-identity-pool="${WIF_POOL}" >/dev/null 2>&1 || \
  gcloud iam workload-identity-pools providers create-oidc "${WIF_PROVIDER}" \
    --project="${PROJECT_ID}" --location=global \
    --workload-identity-pool="${WIF_POOL}" \
    --display-name="GitHub Actions OIDC" \
    --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.repository_owner=assertion.repository_owner" \
    --attribute-condition="assertion.repository == '${GITHUB_REPO}'" \
    --issuer-uri="https://token.actions.githubusercontent.com"

PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
PRINCIPAL_SET="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${WIF_POOL}/attribute.repository/${GITHUB_REPO}"

echo "== binding the repo's WIF principal to impersonate the loader SA =="
gcloud iam service-accounts add-iam-policy-binding "${SA_EMAIL}" \
  --project="${PROJECT_ID}" \
  --role="roles/iam.workloadIdentityUser" \
  --member="${PRINCIPAL_SET}" >/dev/null

PROVIDER_NAME="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${WIF_POOL}/providers/${WIF_PROVIDER}"
echo
echo "Done. For .github/workflows/etl.yml:"
echo "  workload_identity_provider: ${PROVIDER_NAME}"
echo "  service_account:            ${SA_EMAIL}"
