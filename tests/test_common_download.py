"""Tests for the shared HTTP fetch helper."""

from __future__ import annotations

import urllib.error

import pytest

from sanctions_lists_etl.common.download import FetchResult, fetch, strip_query

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


def test_fetch_returns_content_in_memory():
    opener = _Opener(
        _Response(
            b"<a/>", headers={"ETag": '"v1"', "Last-Modified": "Mon, 01 Jan 2026 00:00:00 GMT"}
        )
    )

    result = fetch(_URL, opener=opener)

    assert isinstance(result, FetchResult)
    assert result.content == b"<a/>"
    assert result.size_bytes == len(b"<a/>")
    assert result.url == _URL


def test_fetch_computes_sha256_over_the_streamed_content():
    import hashlib

    payload = b"<a/><b/><c/>"
    result = fetch(_URL, opener=_Opener(_Response(payload)))
    assert result.sha256 == hashlib.sha256(payload).hexdigest()


def test_fetch_sends_no_conditional_headers():
    opener = _Opener(_Response(b"<a/>"))
    fetch(_URL, opener=opener)
    assert opener.request.get_header("If-none-match") is None
    assert opener.request.get_header("If-modified-since") is None


def test_fetch_reraises_http_errors():
    err = urllib.error.HTTPError(_URL, 500, "Server Error", {}, None)
    with pytest.raises(urllib.error.HTTPError):
        fetch(_URL, opener=_Opener(error=err))


def test_fetch_redacts_url_in_result():
    result = fetch(f"{_URL}?token=abc", opener=_Opener(_Response(b"<a/>")))
    assert "abc" not in result.url


def test_fetch_sets_extra_headers():
    opener = _Opener(_Response(b"<a/>"))
    fetch(_URL, headers={"X-Custom": "yes"}, opener=opener)
    assert opener.request.get_header("X-custom") == "yes"
