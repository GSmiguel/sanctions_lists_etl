import pytest

from sanctions_lists_etl.sources.ofac.parser import parse_sdn_advanced


@pytest.fixture(scope="module")
def records(sample_xml):
    return {record.fixed_ref: record for record in parse_sdn_advanced(sample_xml)}


def test_all_party_types_present(records):
    types = {ref: rec.party_type for ref, rec in records.items()}
    assert types == {
        "36": "Entity",
        "2677": "Individual",
        "4238": "Vessel",
        "15432": "Aircraft",
    }


def test_entity_primary_name_and_alias(records):
    entity = records["36"]
    assert entity.primary_name == "AEROCARIBBEAN AIRLINES"
    assert any("AERO-CARIBBEAN" in alias for alias in entity.aliases)


def test_individual_name_is_surname_first(records):
    person = records["2677"]
    assert person.primary_name.startswith("Al-Zomor, ")


def test_individual_features_resolved(records):
    person = records["2677"]
    assert person.nationalities  # nationality country feature
    assert person.birth_dates and person.birth_dates[0].startswith("19")


def test_sanctions_entry_joined_back(records):
    entity = records["36"]
    assert entity.programs == ["CUBA"]
    assert entity.sanctions_lists == ["SDN List"]
    assert entity.listed_on == ["1986-12-10"]


def test_vessel_features_go_to_other_column(records):
    vessel = records["4238"]
    joined = " ".join(vessel.other_features)
    assert "Vessel Flag" in joined


def test_row_serialisation_uses_semicolons(records):
    row = records["36"].to_row()
    assert row["id_ofac"] == "36"
    assert row["tipo"] == "Entity"
    assert "; " in row["enderecos"] or row["enderecos"]


def test_party_type_filter(sample_xml):
    only = parse_sdn_advanced(sample_xml, party_types={"Individual", "Entity"})
    assert {r.party_type for r in only} == {"Individual", "Entity"}
