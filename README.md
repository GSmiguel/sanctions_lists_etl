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

# download a fresh SDN snapshot and write data/output/ofac_sdn.xlsx
uv run sanctions-etl

# parse a local file instead of downloading
uv run sanctions-etl --xml data/raw/sdn_advanced.xml

# individuals and entities only (drop vessels/aircraft)
uv run sanctions-etl --individuals-entities-only --out data/output/parties.xlsx
```

`data/raw/` keeps the downloaded XML plus a `.meta.json` sidecar recording its
SHA-256, size and download timestamp. Everything under `data/` is gitignored.

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

## Development

Package layout: `src/sanctions_lists_etl/` — `download` → `references` → `parser`
→ `excel`, orchestrated by `pipeline`.
