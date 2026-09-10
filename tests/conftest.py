from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def sample_xml() -> Path:
    return FIXTURES / "sample_sdn_advanced.xml"


@pytest.fixture(scope="session")
def sample_eu_xml() -> Path:
    return FIXTURES / "sample_eu_fsf.xml"
