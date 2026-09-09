from xml.etree.ElementTree import iterparse

from sanctions_lists_etl.references import localname, parse_reference_data


def _load(sample_xml):
    for _, elem in iterparse(str(sample_xml), events=("end",)):
        if localname(elem.tag) == "ReferenceValueSets":
            return parse_reference_data(elem)
    raise AssertionError("no ReferenceValueSets in fixture")


def test_party_subtype_resolves_to_readable_type(sample_xml):
    ref = _load(sample_xml)
    resolved = set(ref.party_subtype_to_type.values())
    assert {"Individual", "Entity", "Vessel", "Aircraft"} <= resolved


def test_core_lookups_populated(sample_xml):
    ref = _load(sample_xml)
    assert ref.alias_type["1403"] == "Name"
    assert ref.feature_type["8"] == "Birthdate"
    assert ref.country["11143"] == "Mexico"
    assert ref.list_name["1550"] == "SDN List"
    assert ref.sanctions_type["1"] == "Program"
