import pytest

from sanctions_lists_etl.sources.un.download import (
    UN_CONSOLIDATED_URL,
    redact,
    resolve_url,
)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv("UN_CONSOLIDATED_URL", raising=False)


def test_resolve_url_default():
    assert resolve_url() == UN_CONSOLIDATED_URL


def test_resolve_url_argument_and_env_override(monkeypatch):
    assert resolve_url("https://example.test/list.xml") == "https://example.test/list.xml"
    monkeypatch.setenv("UN_CONSOLIDATED_URL", "https://example.test/env.xml")
    assert resolve_url() == "https://example.test/env.xml"


def test_redact_strips_the_sas_signature():
    signed = "https://blob.example/EN/consolidated.xml?sv=2024-05-04&sig=SECRET%3D"
    assert redact(signed) == "https://blob.example/EN/consolidated.xml (signature redacted)"
    assert "SECRET" not in redact(signed)


def test_redact_leaves_clean_urls_untouched():
    assert redact(UN_CONSOLIDATED_URL) == UN_CONSOLIDATED_URL
