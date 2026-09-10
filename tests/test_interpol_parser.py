import pytest

from sanctions_lists_etl.sources.interpol.parser import parse_interpol


@pytest.fixture(scope="module")
def records(sample_interpol_json):
    return {r.interpol_notice_id: r for r in parse_interpol(sample_interpol_json)}


def test_all_notices_parsed(records):
    assert set(records) == {
        "2020/12345",
        "2021/00001",
        "2019/54321",
        "2026/35448",
        "2015/70000",
        "2011/88000",
    }


def test_notice_type_and_party_type(records):
    assert records["2020/12345"].notice_type == "Red Notice"
    assert records["2020/12345"].party_type == "Individual"
    assert records["2026/35448"].notice_type == "UN Special Notice"
    assert records["2011/88000"].party_type == "Entity"
    assert records["2011/88000"].un_reference == "QDe.001"


def test_primary_name_is_surname_first(records):
    assert records["2020/12345"].primary_name == "TSUROEV, MOVLAT"
    assert records["2019/54321"].primary_name == "SMITH, JOHN ALAN"
    # entity: single name, no comma
    assert records["2011/88000"].primary_name == "EXAMPLE CHARITABLE FOUNDATION"
    # individual with no forename
    assert records["2021/00001"].primary_name == "DOE"


def test_birth_date_normalisation(records):
    assert records["2020/12345"].birth_dates == ["1991-09-24"]
    assert records["2019/54321"].birth_dates == ["1980"]  # 1980/00/00 -> year only
    assert records["2021/00001"].birth_dates == []  # 0000/00/00 -> dropped


def test_countries_are_expanded(records):
    assert records["2020/12345"].nationalities == ["Russia"]
    assert records["2019/54321"].nationalities == ["United States", "United Kingdom"]
    assert "Russia" in records["2020/12345"].birth_places[0]


def test_gender_mapping(records):
    assert records["2020/12345"].genders == ["Male"]
    assert records["2019/54321"].genders == ["Female"]
    assert records["2021/00001"].genders == ["Unknown"]


def test_charges_are_tidied(records):
    charges = records["2020/12345"].to_row()["charges"]
    assert "Participation in the activity of an illegal armed formation" in charges
    # leading "- " bullets dropped, " - " run-ons split on "; "
    assert "Arrestation, enlèvement; Violence commise en réunion." in charges
    assert "[EN: Kidnapping; Group violence.]" in charges
    assert records["2020/12345"].to_row()["warrant_countries"] == "Russia; France"


def test_physical_description(records):
    desc = records["2020/12345"].to_row()["physical_description"]
    assert desc == "1.75 m; eyes: brown; hair: other; Scar on left cheek."
    # weight 0 is treated as unknown and left out
    assert "kg" not in desc
    assert records["2021/00001"].to_row()["physical_description"] == ""


def test_languages_expanded(records):
    assert records["2020/12345"].languages_spoken == ["Chechen", "Russian"]


def test_un_person_aliases_and_documents(records):
    row = records["2026/35448"].to_row()
    assert "DAGALO, ALGONEY HAMDAN" in row["aliases"]
    assert "DAGALO, AL-QONI HAMDAN (b. 1990-08-07)" in row["aliases"]
    assert row["id_documents"].startswith(
        "NATIONAL IDENTIFICATION NR: 784199014302485 (United Arab Emirates)"
    )
    assert "PASSPORT: B00024943 (Sudan) [expires 2031-09-27]" in row["id_documents"]


def test_original_script_and_family_names_become_aliases(records):
    aliases = records["2015/70000"].to_row()["aliases"]
    assert "المثال, تست" in aliases
    assert "AL-SAMPLE TEST (name at birth)" in aliases
    assert "EXAMPLE, MOTHER (mother)" in aliases
    assert "FATHER (father)" in aliases


def test_summary_collapses_whitespace_and_prepends_profession(records):
    remarks = records["2026/35448"].to_row()["remarks"]
    assert "\r" not in remarks and "\n" not in remarks
    assert remarks.startswith("SDi.011 AL-GONEY HAMDAN DAGALO")
    assert records["2015/70000"].to_row()["remarks"] == "Profession: Engineer"


def test_notice_and_image_urls(records):
    assert records["2020/12345"].notice_url.endswith("/red/2020-12345")
    assert records["2020/12345"].image_url.endswith("/images/999")
    assert records["2026/35448"].image_url.endswith("/persons/2026-35448/images")


def test_notice_type_filter(sample_interpol_json):
    red = parse_interpol(sample_interpol_json, notice_types={"red"})
    assert {r.notice_type for r in red} == {"Red Notice"}
    un = parse_interpol(sample_interpol_json, notice_types=("un",))
    assert {r.notice_type for r in un} == {"UN Special Notice"}
    assert {r.party_type for r in un} == {"Individual", "Entity"}
