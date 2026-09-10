import pytest

from sanctions_lists_etl.sources.interpol.parser import parse_interpol


@pytest.fixture(scope="module")
def records(sample_interpol_json):
    return {r.interpol_notice_id: r for r in parse_interpol(sample_interpol_json)}


def test_all_notices_parsed(records):
    assert set(records) == {
        "2026/35448",
        "2015/70000",
        "2019/54321",
        "2020/11111",
        "2011/88000",
        "2013/90000",
    }


def test_notice_type_and_party_type(records):
    assert records["2026/35448"].notice_type == "UN Special Notice"
    assert records["2026/35448"].party_type == "Individual"
    assert records["2011/88000"].party_type == "Entity"


def test_un_reference_is_kept(records):
    assert records["2026/35448"].un_reference == "SDi.011"
    assert records["2011/88000"].un_reference == "QDe.001"


def test_primary_name_is_surname_first(records):
    assert records["2026/35448"].primary_name == "DAGALO, AL-GONEY HAMDAN"
    # person with no forename
    assert records["2019/54321"].primary_name == "SINGLENAME"
    # entity: single name, no comma
    assert records["2011/88000"].primary_name == "EXAMPLE CHARITABLE FOUNDATION"


def test_birth_date_normalisation(records):
    assert records["2026/35448"].birth_dates == ["1990-08-07"]
    assert records["2015/70000"].birth_dates == ["1975"]  # 1975/00/00 -> year only
    assert records["2020/11111"].birth_dates == ["1985-03"]  # 1985/03/00 -> year-month
    assert records["2019/54321"].birth_dates == []  # 0000/00/00 -> dropped


def test_notice_and_image_urls(records):
    assert records["2026/35448"].notice_url.endswith("/un/persons/2026-35448")
    assert records["2026/35448"].image_url.endswith("/un/persons/2026-35448/images")
    # no images link -> empty
    assert records["2019/54321"].image_url == ""


def test_row_shape(records):
    row = records["2026/35448"].to_row()
    assert row == {
        "interpol_notice_id": "2026/35448",
        "un_reference": "SDi.011",
        "notice_type": "UN Special Notice",
        "type": "Individual",
        "primary_name": "DAGALO, AL-GONEY HAMDAN",
        "dates_of_birth": "1990-08-07",
        "notice_url": "https://ws-public.interpol.int/notices/v1/un/persons/2026-35448",
        "image_url": "https://ws-public.interpol.int/notices/v1/un/persons/2026-35448/images",
    }
