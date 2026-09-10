"""Download an OFAC advanced XML export (SDN or Consolidated / Non-SDN).

The Sanctions List Service publishes both lists in the same advanced-XML schema:

    https://sanctionslistservice.ofac.treas.gov/api/download/sdn_advanced.xml
    https://sanctionslistservice.ofac.treas.gov/api/download/cons_advanced.xml

Each endpoint answers with a 302 redirect to a short-lived (1 hour) signed S3
URL, so the download must be performed fresh each run rather than caching the
redirect target.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import shutil
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

SDN_ADVANCED_URL = "https://sanctionslistservice.ofac.treas.gov/api/download/sdn_advanced.xml"
CONS_ADVANCED_URL = "https://sanctionslistservice.ofac.treas.gov/api/download/cons_advanced.xml"

_USER_AGENT = "sanctions-lists-etl/0.1 (+https://github.com/GSmiguel/sanctions_lists_etl)"
_CHUNK = 1 << 20
_PROGRESS_EVERY = 16 << 20  # log a line roughly every 16 MiB


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


def download_advanced_xml(
    dest_dir: Path | str = "data/raw",
    *,
    url: str = SDN_ADVANCED_URL,
    filename: str = "sdn_advanced.xml",
    timeout: float = 300.0,
) -> DownloadResult:
    """Fetch an OFAC advanced-XML export into ``dest_dir`` and record its metadata.

    Works for either the SDN (``url=SDN_ADVANCED_URL``) or the Consolidated /
    Non-SDN (``url=CONS_ADVANCED_URL``) list.  A sibling ``<filename>.meta.json``
    file captures the checksum, size and timestamp so later stages can tell which
    snapshot they are working from.
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / filename
    tmp = dest.with_suffix(dest.suffix + ".part")

    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    hasher = hashlib.sha256()
    size = 0
    started = time.monotonic()
    log.info("downloading %s", url)
    with urllib.request.urlopen(request, timeout=timeout) as response, tmp.open("wb") as fh:
        total = int(response.headers.get("Content-Length") or 0)
        log.info(
            "  %s%s",
            f"{total / (1024 * 1024):.1f} MB" if total else "unknown size",
            "" if response.url == url else f" (redirected to {response.url.split('?')[0]})",
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
        downloaded_at=dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        url=url,
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
