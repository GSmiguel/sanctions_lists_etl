from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "sample_sdn_advanced.xml"


@pytest.fixture(scope="session")
def sample_xml() -> Path:
    return FIXTURE
