import json

import pytest

from sanctions_lists_etl.common.meta import read_meta
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


def test_download_writes_file_and_meta_sidecar(tmp_path):
    payload = b"<Designations><DateGenerated>10/09/2026</DateGenerated></Designations>"
    headers = {"ETag": '"abc123"', "Last-Modified": "Wed, 10 Sep 2026 00:00:00 GMT"}
    response = _FakeResponse(payload, headers)

    result = download_uk_sanctions(tmp_path, opener=_opener(response))

    assert result.path.read_bytes() == payload
    assert result.size_bytes == len(payload)
    assert result.not_modified is False
    meta = json.loads(result.path.with_name(result.path.name + ".meta.json").read_text())
    assert meta["sha256"] == result.sha256
    assert meta["url"] == UK_SANCTIONS_URL
    assert meta["etag"] == '"abc123"'


def test_second_run_with_matching_sha256_reports_not_modified(tmp_path):
    payload = b"<Designations/>"
    download_uk_sanctions(tmp_path, opener=_opener(_FakeResponse(payload)))

    again = download_uk_sanctions(tmp_path, opener=_opener(_FakeResponse(payload)))

    assert again.not_modified is True
    assert read_meta(again.path)["sha256"] == again.sha256
