# sanctions_lists_etl

ETL pipeline for ingesting, normalizing, and consolidating public sanctions lists
(e.g. OFAC SDN + Non-SDN, EU consolidated list, UN Security Council, UK Sanctions
List) plus the INTERPOL–UN Special Notices used for screening.

## Stage 1 — OFAC SDN + Consolidated (Non-SDN)

Downloads OFAC's two **advanced XML** exports — the **SDN** list
(`https://sanctionslistservice.ofac.treas.gov/api/download/sdn_advanced.xml`) and
the **Consolidated / Non-SDN** list
(`https://sanctionslistservice.ofac.treas.gov/api/download/cons_advanced.xml`:
SSI, Non-SDN CMIC, Non-SDN Menu-Based Sanctions, Non-SDN Palestinian Legislative
Council and CAPTA) — and flattens every sanctioned party (individuals, entities,
vessels and aircraft) into a single-sheet Excel workbook, one row per party. The
two lists share a schema, parser and column layout; each is written to its own
workbook (`ofac_sdn.xlsx` / `ofac_consolidated.xlsx`). `--list sdn` /
`--list consolidated` builds just one (default: both).

The advanced format is a relational model (names, addresses, ID documents and
features live in separate structures keyed by id), so the parser first reads the
`ReferenceValueSets` and `Locations` tables, then streams the `DistinctParty`
records, then joins the `SanctionsEntries` (programs, listing dates) back on.

## Stage 2 — EU consolidated list

Downloads the EU **Financial Sanctions Files (FSF)** full XML from the EC FSD web
gate and flattens every `sanctionEntity` — persons and enterprises — into a
single-sheet workbook with the same column layout as the OFAC export (shared
headers wherever the two lists carry the same information), so the two workbooks
line up side by side.

The EU format is flat: no reference tables, every name / birth date / address /
identification / citizenship hangs off the entity with its values in attributes,
so it is a single streaming pass. There is no explicit "primary name" flag, so
the primary name is the lowest-`logicalId` alias (the original listing entry),
preferring a Latin-script one when the lowest-id alias is in another script.

### Access token (credential)

The FSD bot/crawler download authenticates with a `?token=…` query parameter
instead of a login, so **treat it as a secret** — never commit it. Get it from
the download link on <https://webgate.ec.europa.eu/fsd/fsf#!/files> and provide
it one of these ways (checked in order):

- `--token-file PATH` — a file whose contents are the token
- `EU_FSF_TOKEN_FILE` — same, via env var
- `EU_FSF_TOKEN` — the token itself, via env var

`EU_FSF_URL` overrides the whole download URL if the web gate changes. Every log
line and the `.meta.json` sidecar store the URL with the token stripped. See
`.env.example`.

## Stage 3 — UN Security Council Consolidated List

Downloads the UN Security Council **Consolidated List** full XML from
`https://scsanctions.un.org/resources/xml/en/consolidated.xml` and flattens every
listed party — `<INDIVIDUAL>` and `<ENTITY>` — into a single-sheet workbook with
the same column layout as the OFAC and EU exports (shared headers wherever the
lists carry the same information).

The UN format is flat like the EU one (no reference tables): every party carries
its names, aliases, birth dates, addresses and documents inline as child
elements whose values are element *text*. It is a single streaming pass, and the
party type comes straight from the `INDIVIDUAL` / `ENTITY` tag. There is one row
per `REFERENCE_NUMBER` (e.g. `QDi.335`, `IRe.001`) — the UN's own designation
reference, which also encodes individual (`…i.…`) vs entity (`…e.…`) and the
sanctions committee prefix (`QD` = Al-Qaida, `TA` = Taliban, `KP` = DPRK, …). It
is the sort key and the `un_reference_number` column.

The published endpoint answers with a 302 redirect to a short-lived signed Azure
Blob URL, so — like the OFAC endpoint — the file is fetched fresh each run. **No
credential is required.** `UN_CONSOLIDATED_URL` overrides the whole URL; every
log line and the `.meta.json` sidecar store the URL with the signature stripped.

## Stage 4 — INTERPOL UN Special Notices

Crawls the INTERPOL **public notices web service**
(`https://ws-public.interpol.int/notices/v1/un`) — the undocumented JSON backend
behind the UN Special Notice search page on interpol.int — and flattens every
**UN Special Notice** (`INDIVIDUAL` and `ENTITY`) into a single-sheet workbook.
No credential is required.

INTERPOL–UN Special Notices are issued for parties on the **UN Consolidated List**
(stage 3); this export carries INTERPOL's own notice id and photo URL keyed to
the `un_reference` (e.g. `SDi.011`, `QDe.001`), so it cross-references stage 3
rather than duplicating it. It is a screening / photo-lookup aid, not a sanctions
list in its own right.

Only the notices' **summary** rows are pulled — id, name, date of birth,
`un_reference`, notice and image URLs. The per-notice detail records (charges,
aliases, physical description, narrative) are deliberately not fetched.

The service is built for the website, not for export: every query returns **at
most ~160 results and will not paginate past them**, and it honours only the
`name` filter (a substring match). So the crawler sweeps `name` over one letter,
then two letters for any slice still over the cap, and de-duplicates on
`entity_id`; `/un/entities` (~110 rows) comes back in one page and is fetched
directly as a safety net. **Coverage is high but not provably complete** (only
*public* notices are exposed, and the collected-vs-reported gap is logged and
recorded in `.meta.json`). A run makes a few hundred requests (~5 min).

It retries HTTP 403/429/5xx with backoff — the edge (Akamai) rate-limits with 403
and can IP-block for a while, so raise `INTERPOL_REQUEST_DELAY` (seconds, default
0.5) if that happens; once retries are exhausted the crawler fails with a clean
error. `INTERPOL_API_BASE` overrides the service root. The service also rejects
non-browser User-Agents, so this source sends a browser UA. The `.meta.json`
sidecar records the SHA-256, the notice counts and the coverage note.

## Stage 5 — UK Sanctions List

Downloads the FCDO **UK Sanctions List** full XML from
`https://sanctionslist.fcdo.gov.uk/docs/UK-Sanctions-List.xml` and flattens every
`<Designation>` — individuals, entities and ships — into a single-sheet workbook
with the same column layout as the other exports.

This is the UK's autonomous regime (not a mirror of the EU or UN lists). It
**replaced the OFSI "Consolidated List of Asset Freeze Targets"** (`ConList.xml`),
which was frozen on 28 January 2026; the asset-freeze data OFSI used to publish
now lives here (`OFSIGroupID` is carried through as `ofsi_group_id`).

The format is flat like the UN one (no reference tables): every designation
carries its names, aliases, addresses and type-specific details (individual /
entity / ship) inline as child-element text. It is a single streaming pass, and
the party type comes from `<IndividualEntityShip>` (`Ship` is mapped to `Vessel`
to match the OFAC wording). There is one row per `UniqueID` (e.g. `RUS0123`,
`AFG0006`) — the FCDO's own designation reference, which is the sort key and the
`uk_unique_id` column; `UNReferenceNumber` cross-references the UN list where the
designation originates there. The free-text `OtherInformation` field becomes
`remarks` with the INTERPOL–UN Special Notice pointer stripped.

The file is served straight from CloudFront/S3 (~21 MB, no redirect, no signed
query string), so **no credential is required**. `UK_SANCTIONS_URL` overrides the
whole URL.

### Usage

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync

# run every registered source end to end (EU needs EU_FSF_TOKEN set; if it is
# missing the run still produces the other lists and then exits non-zero)
uv run sanctions-etl

# just OFAC
uv run sanctions-etl ofac

# just the EU list
export EU_FSF_TOKEN=...        # or: uv run sanctions-etl eu --token-file ~/.secrets/eu.token
uv run sanctions-etl eu

# just the UN list (no credential needed)
uv run sanctions-etl un

# just the UK Sanctions List (no credential needed)
uv run sanctions-etl uk

# just one OFAC list (default builds both SDN and Non-SDN Consolidated)
uv run sanctions-etl ofac --list sdn
uv run sanctions-etl ofac --list consolidated

# just INTERPOL UN Special Notices (no credential; ~5 min)
uv run sanctions-etl interpol
uv run sanctions-etl interpol --limit 20   # smoke test: keep only 20 notices
uv run sanctions-etl interpol --json data/raw/interpol.json   # parse a local snapshot

# parse a local file instead of downloading
uv run sanctions-etl ofac --xml data/raw/sdn_advanced.xml   # parsed as the SDN list
uv run sanctions-etl eu --xml data/raw/eu_fsf_full.xml
uv run sanctions-etl un --xml data/raw/un_consolidated.xml
uv run sanctions-etl uk --xml data/raw/uk_sanctions_list.xml

# reuse the cached XML in data/raw/ instead of downloading a fresh copy
uv run sanctions-etl ofac --no-download

# restrict party types
uv run sanctions-etl ofac --individuals-entities-only   # drop vessels/aircraft
uv run sanctions-etl eu --persons-only                  # or --entities-only
uv run sanctions-etl un --individuals-only              # or --entities-only
uv run sanctions-etl uk --individuals-only              # or --entities-only / --no-ships

uv run sanctions-etl --list          # show registered sources
uv run sanctions-etl --output-dir OUT --raw-dir RAW   # override paths
uv run sanctions-etl -q ofac         # -q quiet (warnings only), -v debug
```

Progress is logged to stderr as it runs (download progress, parsed-party
counts, Excel write); `-q`/`-v` adjust the level. Top-level flags
(`--output-dir`, `--raw-dir`, `-q`, `-v`) go **before** the source name.

Each source writes to `<output-dir>/` (OFAC → `ofac_sdn.xlsx` +
`ofac_consolidated.xlsx`, EU → `eu_fsf.xlsx`, UN → `un_consolidated.xlsx`,
UK → `uk_sanctions.xlsx`, INTERPOL → `interpol.xlsx`).
`data/raw/` keeps the downloaded source files plus a `.meta.json` sidecar
recording SHA-256, size and download timestamp. Everything under `data/` is
gitignored.

### Output columns

| column | contents |
| --- | --- |
| `ofac_id` | OFAC fixed reference number |
| `type` | Individual / Entity / Vessel / Aircraft |
| `primary_name` | primary name (surname-first for individuals) |
| `aliases` | AKA / FKA / NKA and non-Latin script renderings |
| `dates_of_birth`, `places_of_birth` | birth date / place |
| `nationalities`, `citizenships`, `gender`, `titles` | person attributes |
| `countries`, `addresses` | address countries and full address strings |
| `id_documents` | ID documents (`Type: Number (Country)`) |
| `programs`, `lists`, `listed_on` | sanctions programs, source list, first listing date |
| `emails`, `websites`, `digital_currency_addresses` | contact and digital-currency addresses |
| `other_features` | every other feature (`Feature name: value`) |

Multi-valued cells are joined with `; `.

The EU workbook (`eu_fsf.xlsx`, sheet `EU`) reuses these headers where the data
matches and swaps the rest: `eu_reference_number` / `un_id` replace `ofac_id`,
`programmes` + `regulations` replace `programs` + `lists`, and it adds
`functions`, `phones` and `remarks` (no `nationalities` /
`digital_currency_addresses` / `other_features`).

The UN workbook (`un_consolidated.xlsx`, sheet `UN`) likewise reuses the shared
headers and swaps the rest: `un_reference_number` / `data_id` replace `ofac_id`,
`un_list_type` (the sanctions committee — Al-Qaida, Taliban, DPRK, …) fills the
`programmes` slot, and it adds `name_original_script`, `last_updated`,
`last_reviewed_on` and `interpol_notice`. The free-text `COMMENTS1` field becomes
`remarks` with the "INTERPOL-UN Security Council Special Notice" boilerplate
stripped.

The INTERPOL workbook (`interpol.xlsx`, sheet `INTERPOL`) is thin — only the
notices' summary rows are pulled: `type`, `primary_name` and `dates_of_birth`
line up with the other exports; `interpol_notice_id` replaces `ofac_id`;
`un_reference` ties the row back to the UN Consolidated List (stage 3); and
`notice_type`, `notice_url` and `image_url` are INTERPOL-specific.

The UK workbook (`uk_sanctions.xlsx`, sheet `UK`) reuses the shared headers and
swaps the rest: `uk_unique_id` / `ofsi_group_id` / `un_reference_number` replace
`ofac_id`, `programmes` holds the UK sanctions regime (`RegimeName`), and it adds
`designation_source` (UK / UN / UK|UN), `sanctions_imposed`,
`name_original_script`, `last_updated`, `entity_type` / `parent_companies` /
`subsidiaries`, `vessel_info` and `statement_of_reasons`.

### Tests

```bash
uv run pytest
```

Tests run against trimmed real exports in `tests/fixtures/`:
`sample_sdn_advanced.xml` (4 OFAC parties, one of each type, full reference
tables), `sample_eu_fsf.xml` (5 EU entities covering persons, an enterprise,
a UN cross-listing, ISO / year-range / non-Gregorian birth dates and contact
info) and `sample_un_consolidated.xml` (4 individuals + 3 entities covering
multi-part names, non-Latin scripts, exact / year-range / approximate birth
dates, empty-alias placeholders and a trailing-space reference number).
`sample_interpol.json` (4 UN Special Notice individuals + 2 entities covering
exact / year-only / year-month / missing birth dates, a name with no forename,
and a notice with no photo) and `sample_uk_sanctions.xml` (2 individuals + 2
entities + 1 ship covering multi-part and non-Latin names, `Primary Name
Variation` / weak-alias annotations, the `dd/mm/yyyy` placeholder birth-date
formats, duplicate passport rows, entity parent/subsidiary details, ship IMO /
flag / dimensions and the INTERPOL notice-pointer scrub). The INTERPOL crawler is
tested against an in-memory fake of the web service (`test_interpol_download.py`)
that reproduces the ~160-result cap so the `name` sweep is exercised offline.

## Architecture

```
src/sanctions_lists_etl/
  cli.py         `sanctions-etl` command (subcommand per source, + "all")
  runner.py      source registry + run_all() / run_source()
  base.py        Source / SourceResult — the contract each list implements
  common/
    xmlutils.py  namespace-agnostic XML helpers (shared by all XML sources)
    excel.py     generic single-sheet workbook writer
  sources/
    ofac/        OFAC SDN + Consolidated (Non-SDN)
      download.py  references.py  columns.py  parser.py  pipeline.py
    eu/          EU consolidated list (FSF)
      download.py  columns.py  parser.py  pipeline.py
    un/          UN Security Council Consolidated List
      download.py  columns.py  parser.py  pipeline.py
    uk/          UK Sanctions List (FCDO)
      download.py  columns.py  parser.py  pipeline.py
    interpol/    INTERPOL UN Special Notices (JSON web service)
      download.py  columns.py  parser.py  pipeline.py
```

**Adding a list** (EU consolidated, UN Security Council, ...): create
`sources/<name>/` with a module exporting a `SOURCE` object
(`base.Source`: name, description, a `run(**opts) -> SourceResult` callable, and
optional CLI hooks), then register it in `runner._SOURCES`. The CLI subcommand
and `run_all` pick it up automatically.
