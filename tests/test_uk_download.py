import pytest

from sanctions_lists_etl.sources.uk.download import (
    UK_SANCTIONS_URL,
    download_uk_sanctions,
    resolve_url,
)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv("UK_SANCTIONS_URL", raising=False)


def test_resolve_url_default():
    assert resolve_url() == UK_SANCTIONS_URL


def test_resolve_url_argument_and_env_override(monkeypatch):
    assert resolve_url("https://example.test/list.xml") == "https://example.test/list.xml"
    monkeypatch.setenv("UK_SANCTIONS_URL", "https://example.test/env.xml")
    assert resolve_url() == "https://example.test/env.xml"


class _FakeResponse:
    def __init__(self, payload: bytes, headers: dict | None = None):
        self._chunks = [payload]
        self.headers = {"Content-Length": str(len(payload)), **(headers or {})}
        self.url = UK_SANCTIONS_URL

    def read(self, _size: int = -1) -> bytes:
        return self._chunks.pop(0) if self._chunks else b""

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def _opener(response):
    return lambda _request, _timeout: response


def test_download_returns_content_in_memory():
    payload = b"<Designations><DateGenerated>10/09/2026</DateGenerated></Designations>"
    headers = {"ETag": '"abc123"', "Last-Modified": "Wed, 10 Sep 2026 00:00:00 GMT"}
    response = _FakeResponse(payload, headers)

    result = download_uk_sanctions(opener=_opener(response))

    assert result.content == payload
    assert result.size_bytes == len(payload)
    assert result.url == UK_SANCTIONS_URL


def test_download_computes_sha256():
    import hashlib

    payload = b"<Designations/>"
    result = download_uk_sanctions(opener=_opener(_FakeResponse(payload)))
    assert result.sha256 == hashlib.sha256(payload).hexdigest()
