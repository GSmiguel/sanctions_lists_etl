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

import os
from pathlib import Path

from ...common.download import FetchResult, Opener, fetch, strip_query

UK_SANCTIONS_URL = "https://sanctionslist.fcdo.gov.uk/docs/UK-Sanctions-List.xml"
URL_ENV = "UK_SANCTIONS_URL"

_PROGRESS_EVERY = 8 << 20  # log roughly every 8 MiB (the file is ~21 MiB)

# Back-compat alias: callers historically imported ``DownloadResult`` from here.
DownloadResult = FetchResult


def resolve_url(url: str | None = None) -> str:
    return url or os.environ.get(URL_ENV) or UK_SANCTIONS_URL


def download_uk_sanctions(
    dest_dir: Path | str = "data/raw",
    *,
    url: str | None = None,
    filename: str = "uk_sanctions_list.xml",
    timeout: float = 300.0,
    opener: Opener | None = None,
) -> FetchResult:
    """Fetch the UK Sanctions List XML into ``dest_dir`` and record its metadata."""
    return fetch(
        resolve_url(url),
        Path(dest_dir) / filename,
        timeout=timeout,
        redact=strip_query,
        progress_every=_PROGRESS_EVERY,
        opener=opener,
    )
