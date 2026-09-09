"""Download the OFAC SDN advanced XML export.

The Sanctions List Service endpoint answers with a 302 redirect to a short-lived
(1 hour) signed S3 URL, so the download must be performed fresh each run rather
than caching the redirect target.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import shutil
import urllib.request
from dataclasses import dataclass
from pathlib import Path

SDN_ADVANCED_URL = (
    "https://sanctionslistservice.ofac.treas.gov/api/download/sdn_advanced.xml"
)

_USER_AGENT = "sanctions-lists-etl/0.1 (+https://github.com/GSmiguel/sanctions_lists_etl)"
_CHUNK = 1 << 20


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


def download_sdn_advanced(
    dest_dir: Path | str = "data/raw",
    *,
    url: str = SDN_ADVANCED_URL,
    filename: str = "sdn_advanced.xml",
    timeout: float = 300.0,
) -> DownloadResult:
    """Fetch ``sdn_advanced.xml`` into ``dest_dir`` and record its metadata.

    A sibling ``<filename>.meta.json`` file captures the checksum, size and
    timestamp so later stages can tell which snapshot they are working from.
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / filename
    tmp = dest.with_suffix(dest.suffix + ".part")

    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    hasher = hashlib.sha256()
    size = 0
    with urllib.request.urlopen(request, timeout=timeout) as response, tmp.open("wb") as fh:
        while chunk := response.read(_CHUNK):
            fh.write(chunk)
            hasher.update(chunk)
            size += len(chunk)

    shutil.move(tmp, dest)
    result = DownloadResult(
        path=dest,
        sha256=hasher.hexdigest(),
        size_bytes=size,
        downloaded_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
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
