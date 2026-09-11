from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def sample_xml() -> Path:
    return FIXTURES / "sample_sdn_advanced.xml"


@pytest.fixture(scope="session")
def sample_eu_xml() -> Path:
    return FIXTURES / "sample_eu_fsf.xml"


@pytest.fixture(scope="session")
def sample_un_xml() -> Path:
    return FIXTURES / "sample_un_consolidated.xml"


@pytest.fixture(scope="session")
def sample_uk_xml() -> Path:
    return FIXTURES / "sample_uk_sanctions.xml"
