"""Download the UK Sanctions List (FCDO full XML).

The Foreign, Commonwealth & Development Office publishes the UK Sanctions List at

    https://sanctionslist.fcdo.gov.uk/docs/UK-Sanctions-List.xml

as a plain ~21 MB file (served straight from CloudFront/S3, no redirect and no
signed query string), so unlike the OFAC and UN endpoints it can be fetched
directly.  No credential is required.

This is the live list.  It replaced the OFSI "Consolidated List of Asset Freeze
Targets" (``ConList.xml``), which was frozen on 28 January 2026; the asset-freeze
data it used to carry now lives here (``AssetFreeze`` indicator, ``OFSIGroupID``).

``UK_SANCTIONS_URL`` overrides the whole URL if the endpoint ever moves.
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

UK_SANCTIONS_URL = "https://sanctionslist.fcdo.gov.uk/docs/UK-Sanctions-List.xml"
URL_ENV = "UK_SANCTIONS_URL"

_USER_AGENT = "sanctions-lists-etl/0.1 (+https://github.com/GSmiguel/sanctions_lists_etl)"
_CHUNK = 1 << 20
_PROGRESS_EVERY = 8 << 20  # log roughly every 8 MiB (the file is ~21 MiB)


@dataclass(frozen=True)
class DownloadResult:
    path: Path
    sha256: str
    size_bytes: int
    downloaded_at: str
    url: str

    @property
    def size_mb(self) -> float:
        return self.size_bytes / (1024 * 1024)


def _clean(url: str) -> str:
    """Drop any query string before logging or persisting the URL."""
    split = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((split.scheme, split.netloc, split.path, "", ""))


def resolve_url(url: str | None = None) -> str:
    return url or os.environ.get(URL_ENV) or UK_SANCTIONS_URL


def download_uk_sanctions(
    dest_dir: Path | str = "data/raw",
    *,
    url: str | None = None,
    filename: str = "uk_sanctions_list.xml",
    timeout: float = 300.0,
) -> DownloadResult:
    """Fetch the UK Sanctions List XML into ``dest_dir`` and record its metadata.

    A sibling ``<filename>.meta.json`` captures the checksum, size and timestamp
    so later stages can tell which snapshot they used.
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
    log.info("downloading %s", _clean(start_url))
    with urllib.request.urlopen(request, timeout=timeout) as response, tmp.open("wb") as fh:
        total = int(response.headers.get("Content-Length") or 0)
        log.info("  %s", f"{total / (1024 * 1024):.1f} MB" if total else "unknown size")
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
        url=_clean(start_url),
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
