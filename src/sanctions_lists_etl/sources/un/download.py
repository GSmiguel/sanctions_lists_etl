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

import os
from pathlib import Path

from ...common.download import FetchResult, Opener, fetch, strip_query

UN_CONSOLIDATED_URL = "https://scsanctions.un.org/resources/xml/en/consolidated.xml"
URL_ENV = "UN_CONSOLIDATED_URL"

_PROGRESS_EVERY = 4 << 20  # log roughly every 4 MiB (the file is ~2 MiB)

# Back-compat alias: callers historically imported ``DownloadResult`` from here.
DownloadResult = FetchResult


def redact(url: str) -> str:
    """Drop the query string (the transient SAS signature) from ``url``."""
    return strip_query(url, note="signature redacted")


def resolve_url(url: str | None = None) -> str:
    return url or os.environ.get(URL_ENV) or UN_CONSOLIDATED_URL


def download_un_consolidated(
    dest_dir: Path | str = "data/raw",
    *,
    url: str | None = None,
    filename: str = "un_consolidated.xml",
    timeout: float = 300.0,
    opener: Opener | None = None,
) -> FetchResult:
    """Fetch the UN consolidated list XML into ``dest_dir`` and record its metadata."""
    return fetch(
        resolve_url(url),
        Path(dest_dir) / filename,
        timeout=timeout,
        redact=redact,
        progress_every=_PROGRESS_EVERY,
        opener=opener,
    )
