import pytest

from sanctions_lists_etl.sources.eu.parser import parse_eu_fsf


@pytest.fixture(scope="module")
def records(sample_eu_xml):
    return {r.eu_reference_number: r for r in parse_eu_fsf(sample_eu_xml.read_bytes())}


def test_all_entities_parsed(records):
    assert set(records) == {
        "EU.3579.2",
        "EU.502.12",
        "EU.3953.70",
        "EU.3886.3",
        "EU.3092.36",
    }


def test_subject_type_mapped_to_shared_vocabulary(records):
    assert records["EU.3579.2"].party_type == "Individual"
    assert records["EU.3953.70"].party_type == "Entity"


def test_primary_name_prefers_lowest_id_latin_alias(records):
    # lowest logicalId alias is "Khalid Sheikh MOHAMMED" (id 289), Latin script.
    person = records["EU.3579.2"]
    assert person.primary_name == "Khalid Sheikh MOHAMMED"
    assert "Bin Khalid Fahd Bin Abdallah" in person.aliases


def test_primary_name_skips_non_latin_when_latin_exists(records):
    entity = records["EU.3953.70"]
    assert entity.primary_name == "Parchin Chemical Industries (PCI)"
    # the Farsi rendering is kept as an alias, tagged with its language
    assert any("(FA)" in alias for alias in entity.aliases)


def test_birthdate_iso_and_year_range(records):
    assert "1965-04-14" in records["EU.3579.2"].birth_dates
    assert records["EU.502.12"].to_row()["dates_of_birth"] == "1953-1958"


def test_bare_birthdate_remark_is_not_a_birth_place(records):
    # EU.3092.36 has an ISLAMIC-calendar birthdate whose only detail is the
    # remark "hijri calendar" — that must not leak into places_of_birth.
    assert not any("hijri" in p.lower() for p in records["EU.3092.36"].birth_places)


def test_un_id_and_designation_date(records):
    dorda = records["EU.3886.3"]
    assert dorda.un_id == "LYi.006"
    assert dorda.listed_on == ["2011-02-26"]  # designationDate wins


def test_listed_on_falls_back_to_earliest_regulation(records):
    # no designationDate on EU.3579.2 -> earliest regulationSummary date
    assert records["EU.3579.2"].listed_on == ["2005-11-30"]


def test_contact_info_split_into_channels(records):
    row = records["EU.3953.70"].to_row()
    assert row["websites"] == "http://icig.ir/"
    assert row["phones"].startswith("+98")


def test_identification_flags(records):
    docs = " ".join(records["EU.3092.36"].documents)
    assert "National passport: F654645" in docs
    assert "[expired]" in docs


def test_row_serialisation_uses_semicolons(records):
    row = records["EU.502.12"].to_row()
    assert row["eu_reference_number"] == "EU.502.12"
    assert row["type"] == "Individual"
    assert "; " in row["regulations"]


def test_subject_type_filter(sample_eu_xml):
    only = parse_eu_fsf(sample_eu_xml.read_bytes(), subject_types={"enterprise"})
    assert {r.party_type for r in only} == {"Entity"}
