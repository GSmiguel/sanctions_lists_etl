"""Shared HTTP download: stream to disk, checksum, provenance sidecar.

The OFAC, EU, UN and UK sources each fetch one large file over HTTPS in the same
way — stream it in chunks, SHA-256 as it arrives, write to a ``.part`` file then
move it into place, and drop a ``<file>.meta.json`` alongside.  :func:`fetch` is
that routine.  It also does a conditional request (``If-None-Match`` /
``If-Modified-Since`` from the previous run's sidecar) and, failing that, an
unchanged-content check on the SHA-256, so a caller can tell when the upstream
snapshot has not moved and skip re-parsing / re-loading downstream.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import shutil
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .meta import read_meta, write_meta

log = logging.getLogger(__name__)

_USER_AGENT = "sanctions-lists-etl/0.1 (+https://github.com/GSmiguel/sanctions_lists_etl)"
_CHUNK = 1 << 20
_DEFAULT_PROGRESS_EVERY = 8 << 20
_NOT_MODIFIED = 304
_MiB = 1024 * 1024

# (request, timeout) -> a context manager yielding an object with .read()/.headers/.url
Opener = Callable[[urllib.request.Request, float], Any]


@dataclass(frozen=True)
class FetchResult:
    path: Path
    sha256: str
    size_bytes: int
    downloaded_at: str
    url: str  # already redacted — safe to log or persist
    not_modified: bool = False

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
    dest: Path | str,
    *,
    headers: Mapping[str, str] | None = None,
    timeout: float = 300.0,
    redact: Callable[[str], str] = strip_query,
    progress_every: int = _DEFAULT_PROGRESS_EVERY,
    conditional: bool = True,
    extra_meta: Mapping[str, Any] | None = None,
    opener: Opener | None = None,
) -> FetchResult:
    """Download ``url`` into ``dest`` and refresh ``dest``'s ``.meta.json`` sidecar.

    With ``conditional`` (the default) the previous sidecar's ``etag`` /
    ``last_modified`` are sent back as validators; an HTTP 304 (or a re-download
    whose SHA-256 matches the last run) returns ``FetchResult(not_modified=True)``
    with the cached file left in place.  ``opener`` injects the HTTP layer for
    tests.
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    open_url = opener or _default_opener
    prev = read_meta(dest)
    safe_url = redact(url)

    request_headers: dict[str, str] = {"User-Agent": _USER_AGENT}
    if headers:
        request_headers.update(headers)
    if conditional and dest.exists():
        if isinstance(prev.get("etag"), str):
            request_headers["If-None-Match"] = prev["etag"]
        if isinstance(prev.get("last_modified"), str):
            request_headers["If-Modified-Since"] = prev["last_modified"]

    log.info("downloading %s", safe_url)
    request = urllib.request.Request(url, headers=request_headers)

    try:
        response_cm = open_url(request, timeout)
    except urllib.error.HTTPError as exc:
        if exc.code == _NOT_MODIFIED and dest.exists():
            since = prev.get("downloaded_at", "?")
            log.info("  not modified since %s — keeping cached copy", since)
            return _keep_cached(dest, prev, safe_url, extra_meta)
        raise

    hasher = hashlib.sha256()
    size = 0
    started = time.monotonic()
    tmp = dest.with_suffix(dest.suffix + ".part")
    with response_cm as response, tmp.open("wb") as fh:
        total = int(_header(response, "Content-Length") or 0)
        final_url = getattr(response, "url", url) or url
        redirect = "" if final_url == url else f" (redirected to {redact(final_url)})"
        log.info("  %s%s", f"{total / _MiB:.1f} MB" if total else "unknown size", redirect)
        next_mark = progress_every
        while chunk := response.read(_CHUNK):
            fh.write(chunk)
            hasher.update(chunk)
            size += len(chunk)
            if size >= next_mark:
                pct = f" ({size / total:.0%})" if total else ""
                log.info("  %.0f MB%s", size / _MiB, pct)
                next_mark += progress_every
        etag = _header(response, "ETag")
        last_modified = _header(response, "Last-Modified")

    sha256 = hasher.hexdigest()
    unchanged = bool(prev.get("sha256")) and sha256 == prev["sha256"]
    shutil.move(tmp, dest)
    log.info(
        "downloaded %.1f MB in %.1fs -> %s%s",
        size / _MiB,
        time.monotonic() - started,
        dest,
        "  (content unchanged)" if unchanged else "",
    )

    downloaded_at = _utc_now()
    meta: dict[str, Any] = {
        "sha256": sha256,
        "size_bytes": size,
        "downloaded_at": downloaded_at,
        "url": safe_url,
    }
    if etag:
        meta["etag"] = etag
    if last_modified:
        meta["last_modified"] = last_modified
    if extra_meta:
        meta.update(extra_meta)
    write_meta(dest, meta)

    return FetchResult(dest, sha256, size, downloaded_at, safe_url, not_modified=unchanged)


def _keep_cached(
    dest: Path,
    prev: Mapping[str, Any],
    safe_url: str,
    extra_meta: Mapping[str, Any] | None,
) -> FetchResult:
    meta = dict(prev)
    meta["checked_at"] = _utc_now()
    if extra_meta:
        meta.update(extra_meta)
    write_meta(dest, meta)
    return FetchResult(
        path=dest,
        sha256=str(prev.get("sha256", "")),
        size_bytes=int(prev.get("size_bytes", 0) or 0),
        downloaded_at=str(prev.get("downloaded_at", "")),
        url=safe_url,
        not_modified=True,
    )


def _header(response: Any, name: str) -> str | None:
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    return headers.get(name)
