# sanctions_lists_etl

Consolidates the major international sanctions / restrictive-party lists into
a single, always-current dataset for compliance screening:

- **OFAC** (US Treasury) — SDN + Consolidated (Non-SDN)
- **EU** consolidated financial sanctions list
- **UN** Security Council Consolidated List
- **UK** Sanctions List (FCDO)

Each run downloads the latest copy of every list, normalizes the four
different formats into one shared row structure, and (optionally) loads the
result into BigQuery. Everything happens in memory — nothing is downloaded or
cached to disk.

## Running it locally

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync

uv run sanctions-etl              # every list
uv run sanctions-etl ofac         # just one (ofac / eu / un / uk)
uv run sanctions-etl --list       # see all registered sources

# also load into BigQuery
uv sync --extra bigquery
BQ_PROJECT=sanctions-screening-508311 uv run sanctions-etl --bigquery
```

The EU list needs an `EU_FSF_TOKEN` (see `.env.example`); OFAC, UN and UK
need no credentials.

## Triggering the daily screening run

The pipeline runs automatically every day via the **`etl`** GitHub Actions
workflow, loading straight into BigQuery. To run it on demand instead of
waiting for the schedule:

```bash
gh workflow run etl.yml
```

(or GitHub → **Actions → etl → Run workflow**).

## Where the data lands

BigQuery project **`sanctions-screening-508311`**, dataset **`sanctions`**:

| table | contents |
| --- | --- |
| `entries` | current state only — one row per party, kept current via a per-source MERGE (no daily copies); `first_seen_date`/`last_seen_date` give a lightweight history without the storage cost |
| `entries_current` | plain view over `entries`, kept for naming stability — query either one |
| `entries_staging` | transient load buffer the sink MERGEs from; not meant to be queried |
| `snapshot_manifest` | tracks each source's most recent load date, informational only |

## Development

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

CI (`.github/workflows/ci.yml`) runs all three on every pull request.
