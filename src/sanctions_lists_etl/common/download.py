"""Shared HTTP download: fetch into memory, checksum while streaming.

The OFAC, EU, UN and UK sources each fetch one large file over HTTPS in the same
way — stream it in chunks, SHA-256 as it arrives, and hand back the assembled
bytes.  :func:`fetch` is that routine.  Nothing is written to disk here; callers
that want a file on disk (tests, manual debugging) write ``result.content``
themselves.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import time
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

log = logging.getLogger(__name__)

_USER_AGENT = "sanctions-lists-etl/0.1 (+https://github.com/GSmiguel/sanctions_lists_etl)"
_CHUNK = 1 << 20
_DEFAULT_PROGRESS_EVERY = 8 << 20
_MiB = 1024 * 1024

# (request, timeout) -> a context manager yielding an object with .read()/.headers/.url
Opener = Callable[[urllib.request.Request, float], Any]


@dataclass(frozen=True)
class FetchResult:
    content: bytes
    sha256: str
    size_bytes: int
    downloaded_at: str
    url: str  # already redacted — safe to log or persist

    @property
    def size_mb(self) -> float:
        return self.size_bytes / _MiB


def strip_query(url: str, *, note: str = "query redacted") -> str:
    """Drop the query string (tokens, SAS signatures) before logging or persisting."""
    split = urlsplit(url)
    clean = urlunsplit((split.scheme, split.netloc, split.path, "", ""))
    return f"{clean} ({note})" if split.query else clean


def _default_opener(request: urllib.request.Request, timeout: float) -> Any:
    return urllib.request.urlopen(request, timeout=timeout)


def _utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def fetch(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    timeout: float = 300.0,
    redact: Callable[[str], str] = strip_query,
    progress_every: int = _DEFAULT_PROGRESS_EVERY,
    opener: Opener | None = None,
) -> FetchResult:
    """Download ``url`` into memory and return its bytes with provenance.

    ``opener`` injects the HTTP layer for tests — it is called as
    ``opener(request, timeout)`` and must return a context manager yielding an
    object with ``.read()`` / ``.headers`` / ``.url``, the same shape
    ``urllib.request.urlopen`` returns.
    """
    open_url = opener or _default_opener
    safe_url = redact(url)

    request_headers: dict[str, str] = {"User-Agent": _USER_AGENT}
    if headers:
        request_headers.update(headers)

    log.info("downloading %s", safe_url)
    request = urllib.request.Request(url, headers=request_headers)

    hasher = hashlib.sha256()
    buffer = bytearray()
    started = time.monotonic()
    with open_url(request, timeout) as response:
        total = int(_header(response, "Content-Length") or 0)
        final_url = getattr(response, "url", url) or url
        redirect = "" if final_url == url else f" (redirected to {redact(final_url)})"
        log.info("  %s%s", f"{total / _MiB:.1f} MB" if total else "unknown size", redirect)
        next_mark = progress_every
        while chunk := response.read(_CHUNK):
            buffer.extend(chunk)
            hasher.update(chunk)
            if len(buffer) >= next_mark:
                pct = f" ({len(buffer) / total:.0%})" if total else ""
                log.info("  %.0f MB%s", len(buffer) / _MiB, pct)
                next_mark += progress_every

    size = len(buffer)
    sha256 = hasher.hexdigest()
    log.info("downloaded %.1f MB in %.1fs", size / _MiB, time.monotonic() - started)

    return FetchResult(bytes(buffer), sha256, size, _utc_now(), safe_url)


def _header(response: Any, name: str) -> str | None:
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    return headers.get(name)
