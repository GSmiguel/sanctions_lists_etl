# sanctions_lists_etl

ETL pipeline for ingesting, normalizing, and consolidating public sanctions lists
(e.g. OFAC SDN, EU consolidated list, UN Security Council).

## Stage 1 — OFAC SDN

Downloads the OFAC **SDN advanced XML** export
(`https://sanctionslistservice.ofac.treas.gov/api/download/sdn_advanced.xml`) and
flattens every sanctioned party — individuals, entities, vessels and aircraft —
into a single-sheet Excel workbook, one row per party.

The advanced format is a relational model (names, addresses, ID documents and
features live in separate structures keyed by id), so the parser first reads the
`ReferenceValueSets` and `Locations` tables, then streams the `DistinctParty`
records, then joins the `SanctionsEntries` (programs, listing dates) back on.

### Usage

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync

# run every registered source end to end
uv run sanctions-etl

# just OFAC
uv run sanctions-etl ofac

# parse a local file instead of downloading
uv run sanctions-etl ofac --xml data/raw/sdn_advanced.xml

# individuals and entities only (drop vessels/aircraft)
uv run sanctions-etl ofac --individuals-entities-only

uv run sanctions-etl --list          # show registered sources
uv run sanctions-etl --output-dir OUT --raw-dir RAW   # override paths
```

Each source writes `<output-dir>/<source>.xlsx` (OFAC → `data/output/ofac_sdn.xlsx`).
`data/raw/` keeps the downloaded source files plus a `.meta.json` sidecar
recording SHA-256, size and download timestamp. Everything under `data/` is
gitignored.

### Output columns

| column | contents |
| --- | --- |
| `id_ofac` | OFAC fixed reference number |
| `tipo` | Individual / Entity / Vessel / Aircraft |
| `nome_principal` | primary name (surname-first for individuals) |
| `nomes_alternativos` | AKA / FKA / NKA and non-Latin script renderings |
| `data_nascimento`, `local_nascimento` | birth date / place |
| `nacionalidades`, `cidadanias`, `genero`, `titulos` | person attributes |
| `paises`, `enderecos` | address countries and full address strings |
| `documentos` | ID documents (`Type: Number (Country)`) |
| `programas`, `listas`, `data_listagem` | sanctions programs, source list, first listing date |
| `emails`, `websites`, `enderecos_cripto` | contact and digital-currency addresses |
| `outras_caracteristicas` | every other feature (`Feature name: value`) |

Multi-valued cells are joined with `; `.

### Tests

```bash
uv run pytest
```

Tests run against `tests/fixtures/sample_sdn_advanced.xml`, a trimmed real export
(4 parties, one of each type) with the full reference tables.

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
    ofac/        OFAC SDN
      download.py  references.py  columns.py  parser.py  pipeline.py
```

**Adding a list** (EU consolidated, UN Security Council, ...): create
`sources/<name>/` with a module exporting a `SOURCE` object
(`base.Source`: name, description, a `run(**opts) -> SourceResult` callable, and
optional CLI hooks), then register it in `runner._SOURCES`. The CLI subcommand
and `run_all` pick it up automatically.
