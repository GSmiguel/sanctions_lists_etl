"""Download an OFAC advanced XML export (SDN or Consolidated / Non-SDN).

The Sanctions List Service publishes both lists in the same advanced-XML schema:

    https://sanctionslistservice.ofac.treas.gov/api/download/sdn_advanced.xml
    https://sanctionslistservice.ofac.treas.gov/api/download/cons_advanced.xml

Each endpoint answers with a 302 redirect to a short-lived (1 hour) signed S3
URL, so the download must be performed fresh each run rather than caching the
redirect target.  No credential is required.
"""

from __future__ import annotations

from pathlib import Path

from ...common.download import FetchResult, Opener, fetch

SDN_ADVANCED_URL = "https://sanctionslistservice.ofac.treas.gov/api/download/sdn_advanced.xml"
CONS_ADVANCED_URL = "https://sanctionslistservice.ofac.treas.gov/api/download/cons_advanced.xml"

_PROGRESS_EVERY = 16 << 20  # log a line roughly every 16 MiB

# Back-compat alias: callers historically imported ``DownloadResult`` from here.
DownloadResult = FetchResult


def download_advanced_xml(
    dest_dir: Path | str = "data/raw",
    *,
    url: str = SDN_ADVANCED_URL,
    filename: str = "sdn_advanced.xml",
    timeout: float = 300.0,
    opener: Opener | None = None,
) -> FetchResult:
    """Fetch an OFAC advanced-XML export into ``dest_dir`` and record its metadata.

    Works for either the SDN (``url=SDN_ADVANCED_URL``) or the Consolidated /
    Non-SDN (``url=CONS_ADVANCED_URL``) list.  The sibling ``<filename>.meta.json``
    captures the checksum, size, timestamp and HTTP validators so a later run can
    tell whether the snapshot moved.
    """
    return fetch(
        url,
        Path(dest_dir) / filename,
        timeout=timeout,
        progress_every=_PROGRESS_EVERY,
        opener=opener,
    )
