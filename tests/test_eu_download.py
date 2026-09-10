import pytest

from sanctions_lists_etl.sources.eu.download import (
    EU_FSF_BASE_URL,
    EuFsfTokenError,
    redact,
    resolve_token,
    resolve_url,
)

_ENV_VARS = ("EU_FSF_TOKEN", "EU_FSF_TOKEN_FILE", "EU_FSF_URL")


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_redact_strips_the_token():
    assert redact(f"{EU_FSF_BASE_URL}?token=s3cr3t") == f"{EU_FSF_BASE_URL} (token redacted)"
    assert "s3cr3t" not in redact(f"{EU_FSF_BASE_URL}?token=s3cr3t")


def test_resolve_token_prefers_argument():
    assert resolve_token("  abc  ") == "abc"


def test_resolve_token_from_env(monkeypatch):
    monkeypatch.setenv("EU_FSF_TOKEN", "envtoken")
    assert resolve_token() == "envtoken"


def test_resolve_token_from_file(monkeypatch, tmp_path):
    token_file = tmp_path / "token.txt"
    token_file.write_text("filetoken\n")
    monkeypatch.setenv("EU_FSF_TOKEN_FILE", str(token_file))
    assert resolve_token() == "filetoken"


def test_resolve_token_missing_raises():
    with pytest.raises(EuFsfTokenError):
        resolve_token()


def test_resolve_url_embeds_token_and_url_override(monkeypatch):
    assert resolve_url(token="xyz") == f"{EU_FSF_BASE_URL}?token=xyz"
    monkeypatch.setenv("EU_FSF_URL", "https://example.test/full.xml")
    assert resolve_url(token="xyz") == "https://example.test/full.xml"
