import pytest

from sanctions_lists_etl.sources.un.parser import parse_un_consolidated


@pytest.fixture(scope="module")
def records(sample_un_xml):
    return {r.un_reference_number: r for r in parse_un_consolidated(sample_un_xml)}


def test_all_parties_parsed(records):
    assert set(records) == {
        "QDi.335",
        "QDi.314",
        "QDi.356",
        "TAi.019",
        "QDe.144",
        "IRe.001",
        "KPe.033",
    }


def test_reference_number_is_trimmed(records):
    # <REFERENCE_NUMBER>KPe.033 </REFERENCE_NUMBER> has a trailing space in the feed.
    assert "KPe.033" in records
    assert records["KPe.033"].data_id == "6908563"


def test_party_type_from_tag(records):
    assert records["QDi.335"].party_type == "Individual"
    assert records["QDe.144"].party_type == "Entity"


def test_primary_name_joins_ordered_name_parts(records):
    assert records["QDi.335"].primary_name == "‘ABD AL-RAHMAN KHALAF ‘UBAYD JUDAY’ AL-‘ANIZI"
    assert records["QDe.144"].primary_name == "ABDALLAH AZZAM BRIGADES (AAB)"


def test_name_original_script_kept_separate(records):
    assert records["QDi.314"].name_original_script == "عبد الرحمن ولد العامر"
    assert records["QDi.314"].primary_name == "ABDERRAHMANE OULD EL AMAR"


def test_alias_quality_annotations(records):
    row = records["QDi.335"].to_row()["aliases"]
    assert "Abu Usama (low quality)" in row
    assert "‘Abd al-Rahman Khalaf al-Anizi" in row  # "Good" -> no annotation
    # empty <ALIAS_NAME/> placeholder rows are dropped
    assert records["IRe.001"].to_row()["aliases"] == ""


def test_alias_note_is_appended(records):
    assert "Nik Mohammad — previously listed as" in records["TAi.019"].aliases


def test_birthdate_exact_year_range_and_approx(records):
    assert records["QDi.335"].birth_dates == ["1973-03-06"]
    assert records["QDi.314"].birth_dates == ["1977-1982"]
    assert records["TAi.019"].birth_dates == ["approx. 1957"]


def test_place_of_birth_joined(records):
    assert records["QDi.356"].birth_places == [
        "Glasgow, Scotland, United Kingdom of Great Britain and Northern Ireland"
    ]


def test_gender_from_element_and_from_comment(records):
    assert records["QDi.356"].genders == ["Female"]  # <GENDER> element
    # QDi.356's comment also says "Sex: female" — element wins, no duplicate
    assert records["QDi.356"].to_row()["gender"] == "Female"


def test_title_and_designation_split(records):
    row = records["TAi.019"].to_row()
    assert row["titles"] == "Maulavi"
    assert row["functions"] == "Deputy Minister of Commerce under the Taliban regime"


def test_address_country_and_note(records):
    row = records["QDi.335"].to_row()
    assert row["countries"] == "Syrian Arab Republic"
    assert "located in since 2013" in row["addresses"]


def test_document_rendering(records):
    assert records["QDi.335"].documents == [
        "National Identification Number: 273030601222 (Kuwait)"
    ]
    passport = records["QDi.356"].documents[0]
    assert passport.startswith(
        "Passport: 720134834 (United Kingdom of Great Britain and Northern Ireland)"
    )
    assert "[issued 2012-06-27]" in passport
    assert "(expires on 27 Jun. 2022)" in passport


def test_un_list_type_fills_programmes(records):
    assert records["KPe.033"].to_row()["programmes"] == "DPRK"
    assert records["QDi.335"].to_row()["lists"] == "UN List"


def test_listing_dates(records):
    row = records["QDi.335"].to_row()
    assert row["listed_on"] == "2014-09-23"
    assert row["last_updated"] == "2017-02-15; 2019-05-01; 2022-11-08; 2023-02-02"
    assert row["last_reviewed_on"] == "2019-02-21; 2022-11-08"


def test_interpol_notice_only_when_linked(records):
    assert records["QDi.335"].interpol_notice.endswith("View-UN-Notices-Individuals")
    assert records["IRe.001"].interpol_notice == ""


def test_comments_strip_interpol_boilerplate(records):
    remarks = records["QDi.335"].to_row()["remarks"]
    assert remarks.startswith("A sentence of imprisonment for 15 years")
    assert remarks.endswith("in Syria and Iraq")
    assert "INTERPOL" not in remarks
    # the "Photo available for inclusion in the ... Special Notice" phrase is also
    # dropped when it trails the comment
    qdi356 = records["QDi.356"].to_row()["remarks"]
    assert qdi356.endswith("Sex: female")
    assert "Photo available" not in qdi356
    # multi-line comment is collapsed to a single line
    assert "\n" not in records["IRe.001"].to_row()["remarks"]


def test_subject_type_filter(sample_un_xml):
    only = parse_un_consolidated(sample_un_xml, subject_types={"entity"})
    assert {r.party_type for r in only} == {"Entity"}
