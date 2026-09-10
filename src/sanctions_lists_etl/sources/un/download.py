"""Download the UN Security Council Consolidated List (full XML).

The Security Council publishes the list at

    https://scsanctions.un.org/resources/xml/en/consolidated.xml

which answers with a 302 redirect to a short-lived signed Azure Blob URL (a
``?sv=...&sig=...`` SAS query string), so — like the OFAC endpoint — the download
has to be performed fresh each run rather than caching the redirect target.  No
credential is required; the signature is minted by the redirect.  Every log line
and the ``.meta.json`` sidecar store the URL with the query string stripped so
the transient signature is never persisted.

``UN_CONSOLIDATED_URL`` overrides the whole URL if the endpoint ever moves.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import os
import shutil
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

UN_CONSOLIDATED_URL = "https://scsanctions.un.org/resources/xml/en/consolidated.xml"
URL_ENV = "UN_CONSOLIDATED_URL"

_USER_AGENT = "sanctions-lists-etl/0.1 (+https://github.com/GSmiguel/sanctions_lists_etl)"
_CHUNK = 1 << 20
_PROGRESS_EVERY = 4 << 20  # log roughly every 4 MiB (the file is ~2 MiB)


@dataclass(frozen=True)
class DownloadResult:
    path: Path
    sha256: str
    size_bytes: int
    downloaded_at: str
    url: str  # already redacted — safe to log or persist

    @property
    def size_mb(self) -> float:
        return self.size_bytes / (1024 * 1024)


def redact(url: str) -> str:
    """Drop the query string (the transient SAS signature) from ``url``."""
    split = urllib.parse.urlsplit(url)
    clean = urllib.parse.urlunsplit((split.scheme, split.netloc, split.path, "", ""))
    return f"{clean} (signature redacted)" if split.query else clean


def resolve_url(url: str | None = None) -> str:
    return url or os.environ.get(URL_ENV) or UN_CONSOLIDATED_URL


def download_un_consolidated(
    dest_dir: Path | str = "data/raw",
    *,
    url: str | None = None,
    filename: str = "un_consolidated.xml",
    timeout: float = 300.0,
) -> DownloadResult:
    """Fetch the UN consolidated list XML into ``dest_dir`` and record its metadata.

    A sibling ``<filename>.meta.json`` captures the checksum, size and timestamp
    (and the *redacted* URL) so later stages can tell which snapshot they used.
    """
    start_url = resolve_url(url)

    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / filename
    tmp = dest.with_suffix(dest.suffix + ".part")

    request = urllib.request.Request(start_url, headers={"User-Agent": _USER_AGENT})
    hasher = hashlib.sha256()
    size = 0
    started = time.monotonic()
    log.info("downloading %s", redact(start_url))
    with urllib.request.urlopen(request, timeout=timeout) as response, tmp.open("wb") as fh:
        total = int(response.headers.get("Content-Length") or 0)
        log.info(
            "  %s%s",
            f"{total / (1024 * 1024):.1f} MB" if total else "unknown size",
            "" if response.url == start_url else f" (redirected to {redact(response.url)})",
        )
        next_mark = _PROGRESS_EVERY
        while chunk := response.read(_CHUNK):
            fh.write(chunk)
            hasher.update(chunk)
            size += len(chunk)
            if size >= next_mark:
                pct = f" ({size / total:.0%})" if total else ""
                log.info("  %.0f MB%s", size / (1024 * 1024), pct)
                next_mark += _PROGRESS_EVERY

    shutil.move(tmp, dest)
    log.info(
        "downloaded %.1f MB in %.1fs -> %s",
        size / (1024 * 1024),
        time.monotonic() - started,
        dest,
    )
    result = DownloadResult(
        path=dest,
        sha256=hasher.hexdigest(),
        size_bytes=size,
        downloaded_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        url=redact(start_url),
    )
    meta = dest.with_name(dest.name + ".meta.json")
    meta.write_text(
        json.dumps(
            {
                "sha256": result.sha256,
                "size_bytes": result.size_bytes,
                "downloaded_at": result.downloaded_at,
                "url": result.url,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return result
