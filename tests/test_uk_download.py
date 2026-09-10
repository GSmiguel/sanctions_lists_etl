import json

import pytest

from sanctions_lists_etl.sources.uk import download as uk_download
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
    def __init__(self, payload: bytes):
        self._chunks = [payload]
        self.headers = {"Content-Length": str(len(payload))}
        self.url = UK_SANCTIONS_URL

    def read(self, _size: int = -1) -> bytes:
        return self._chunks.pop(0) if self._chunks else b""

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def test_download_writes_file_and_meta_sidecar(tmp_path, monkeypatch):
    payload = b"<Designations><DateGenerated>10/09/2026</DateGenerated></Designations>"
    monkeypatch.setattr(
        uk_download.urllib.request,
        "urlopen",
        lambda *a, **k: _FakeResponse(payload),
    )

    result = download_uk_sanctions(tmp_path)

    assert result.path.read_bytes() == payload
    assert result.size_bytes == len(payload)
    meta = json.loads(result.path.with_name(result.path.name + ".meta.json").read_text())
    assert meta["sha256"] == result.sha256
    assert meta["url"] == UK_SANCTIONS_URL
