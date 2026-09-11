import pytest

from sanctions_lists_etl.sources.uk.parser import parse_uk_sanctions


@pytest.fixture(scope="module")
def records(sample_uk_xml):
    return {r.uk_unique_id: r for r in parse_uk_sanctions(sample_uk_xml.read_bytes())}


def test_all_designations_parsed(records):
    assert set(records) == {"AFG0001", "AFG0006", "BEL0107", "DPR0075", "AQD0195"}


def test_identity_and_cross_reference_columns(records):
    row = records["AFG0001"].to_row()
    assert row["uk_unique_id"] == "AFG0001"
    assert row["ofsi_group_id"] == "12703"
    assert row["un_reference_number"] == "TAe.010"


def test_ship_is_mapped_to_vessel(records):
    assert records["DPR0075"].party_type == "Vessel"
    assert records["AFG0006"].party_type == "Individual"
    assert records["BEL0107"].party_type == "Entity"


def test_subject_type_filter(sample_uk_xml):
    content = sample_uk_xml.read_bytes()
    kinds = {
        r.party_type for r in parse_uk_sanctions(content, subject_types=("INDIVIDUAL", "ENTITY"))
    }
    assert kinds == {"Individual", "Entity"}


def test_primary_name_joins_ordered_parts(records):
    assert records["AFG0006"].primary_name == "MOHAMMAD HASSAN AKHUND"
    assert records["DPR0075"].primary_name == "Petrel 8"


def test_name_type_variation_becomes_annotated_alias(records):
    assert "Mohammad Akhwand (primary name variation)" in records["AFG0006"].aliases


def test_alias_strength_low_quality_is_flagged(records):
    aliases = records["BEL0107"].aliases
    assert "BNK UK Limited" in aliases  # "Good quality a.k.a" -> no annotation
    assert "BNK (low quality)" in aliases


def test_non_latin_name_kept_separate(records):
    assert records["AFG0006"].name_original_script == "محمد حسن آخوند"
    assert records["AFG0006"].primary_name.isascii()


def test_dob_format_matrix(records):
    # full date -> ISO; "dd/mm/YYYY" placeholder -> year; bare year -> year
    assert records["AFG0006"].birth_dates == ["1958-05-12", "1945", "1946"]
    assert records["AQD0195"].birth_dates == ["1972"]


def test_dates_are_normalised_to_iso(records):
    assert records["AFG0001"].to_row()["listed_on"] == "2012-06-29"
    assert records["AFG0001"].to_row()["last_updated"] == "2026-08-04"


def test_sanctions_imposed_is_split_on_pipe(records):
    assert records["AFG0006"].sanctions_imposed == ["Asset freeze", "Travel Ban"]
    assert records["AFG0006"].designation_source == "UK|UN"


def test_regime_name_fills_the_programmes_slot(records):
    assert (
        records["AFG0001"].to_row()["programmes"]
        == "The Afghanistan (Sanctions) (EU Exit) Regulations 2020"
    )


def test_addresses_join_lines_and_collect_countries(records):
    row = records["AFG0001"].to_row()
    assert "Ansari Market, 2nd Floor, Nimroz Province, Afghanistan" in row["addresses"]
    assert row["countries"] == "Afghanistan; United Arab Emirates"


def test_passport_entries_are_deduped(records):
    # the FCDO feed repeats identical passport rows; the flattened cell collapses them
    docs = records["AFG0006"].to_row()["id_documents"]
    assert docs.count("passport number P04581926") == 1
    assert "National ID: 2132370" in docs


def test_entity_details_are_extracted(records):
    r = records["BEL0107"]
    assert r.entity_type == ["Oil trading company"]
    assert r.parent_companies == ["CJSC Belarusian Oil Company", "Belneftekhim"]
    assert r.subsidiaries == ["BNK (Deutschland) GmbH"]
    assert "Business reg.: UK Company no. 06527449" in r.documents
    assert r.to_row()["statement_of_reasons"].startswith("BNK (UK) Ltd is controlled by")


def test_ship_details_are_extracted(records):
    r = records["DPR0075"]
    assert "IMO 9562233" in r.documents  # the "IMO" prefix is not doubled
    assert "Comoros" in r.address_countries
    assert "Global United Shipping India" in r.positions
    assert r.vessel_info == (
        "Type: Bulk Carrier; Tonnage: 7078; Length: 134.5; Previous flag: India"
    )


def test_interpol_notice_boilerplate_is_scrubbed_from_remarks(records):
    for uid in ("AFG0001", "AFG0006", "AQD0195"):
        remarks = records[uid].to_row()["remarks"]
        assert "INTERPOL" not in remarks
        assert "web link" not in remarks
        assert "interpol.int" not in remarks
    # information that merely follows the boilerplate is preserved
    assert "concluded on 13 May 2010" in records["AQD0195"].to_row()["remarks"]
