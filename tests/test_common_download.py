"""Tests for the shared HTTP fetch helper."""

from __future__ import annotations

import urllib.error

import pytest

from sanctions_lists_etl.common.download import FetchResult, fetch, strip_query
from sanctions_lists_etl.common.meta import read_meta

_URL = "https://example.test/list.xml"


class _Response:
    def __init__(self, payload: bytes, *, headers: dict | None = None, url: str = _URL):
        self._chunks = [payload]
        self.headers = {"Content-Length": str(len(payload)), **(headers or {})}
        self.url = url

    def read(self, _size: int = -1) -> bytes:
        return self._chunks.pop(0) if self._chunks else b""

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class _Opener:
    """Records the request it is handed and returns a canned response (or raises)."""

    def __init__(self, response=None, *, error: urllib.error.HTTPError | None = None):
        self._response = response
        self._error = error
        self.request = None

    def __call__(self, request, _timeout):
        self.request = request
        if self._error is not None:
            raise self._error
        return self._response


def test_strip_query_removes_credentials():
    assert strip_query(f"{_URL}?token=secret") == f"{_URL} (query redacted)"
    assert "secret" not in strip_query(f"{_URL}?token=secret")
    assert strip_query(_URL) == _URL
    assert strip_query(f"{_URL}?x=1", note="sig redacted") == f"{_URL} (sig redacted)"


def test_fetch_writes_file_and_meta(tmp_path):
    dest = tmp_path / "list.xml"
    opener = _Opener(
        _Response(
            b"<a/>", headers={"ETag": '"v1"', "Last-Modified": "Mon, 01 Jan 2026 00:00:00 GMT"}
        )
    )

    result = fetch(_URL, dest, opener=opener)

    assert isinstance(result, FetchResult)
    assert dest.read_bytes() == b"<a/>"
    assert result.not_modified is False
    meta = read_meta(dest)
    assert meta["sha256"] == result.sha256
    assert meta["etag"] == '"v1"'
    assert meta["last_modified"] == "Mon, 01 Jan 2026 00:00:00 GMT"
    assert meta["url"] == _URL


def test_fetch_sends_validators_from_previous_meta(tmp_path):
    dest = tmp_path / "list.xml"
    fetch(_URL, dest, opener=_Opener(_Response(b"<a/>", headers={"ETag": '"v1"'})))

    opener = _Opener(_Response(b"<b/>", headers={"ETag": '"v2"'}))
    fetch(_URL, dest, opener=opener)

    assert opener.request.get_header("If-none-match") == '"v1"'


def test_fetch_304_keeps_cached_copy(tmp_path):
    dest = tmp_path / "list.xml"
    first = fetch(_URL, dest, opener=_Opener(_Response(b"<a/>", headers={"ETag": '"v1"'})))

    not_modified = urllib.error.HTTPError(_URL, 304, "Not Modified", {}, None)
    result = fetch(_URL, dest, opener=_Opener(error=not_modified))

    assert result.not_modified is True
    assert result.sha256 == first.sha256
    assert dest.read_bytes() == b"<a/>"
    assert "checked_at" in read_meta(dest)


def test_fetch_identical_content_reports_not_modified(tmp_path):
    dest = tmp_path / "list.xml"
    fetch(_URL, dest, opener=_Opener(_Response(b"<a/>")))

    result = fetch(_URL, dest, opener=_Opener(_Response(b"<a/>")))

    assert result.not_modified is True


def test_fetch_reraises_other_http_errors(tmp_path):
    err = urllib.error.HTTPError(_URL, 500, "Server Error", {}, None)
    with pytest.raises(urllib.error.HTTPError):
        fetch(_URL, tmp_path / "list.xml", opener=_Opener(error=err))


def test_fetch_redacts_url_in_meta(tmp_path):
    dest = tmp_path / "list.xml"
    result = fetch(f"{_URL}?token=abc", dest, opener=_Opener(_Response(b"<a/>")))
    assert "abc" not in result.url
    assert "abc" not in read_meta(dest)["url"]
