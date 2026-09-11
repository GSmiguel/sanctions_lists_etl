"""Download the EU consolidated financial sanctions list (FSF full XML).

The EU FSD web gate exposes a bot/crawler download at

    https://webgate.ec.europa.eu/fsd/fsf/public/files/xmlFullSanctionsList_1_1/content?token=<TOKEN>

The ``token`` query parameter is a **credential**: it authenticates the request
in place of a normal login, so it must never be committed to the repository or
written into a build artifact.  This module only ever reads it from the
environment (``EU_FSF_TOKEN``) or a file pointed at by ``EU_FSF_TOKEN_FILE`` /
``--token-file``, and every log line stores the URL with the query string
stripped.
"""

from __future__ import annotations

import os
import urllib.parse
from pathlib import Path

from ...common.download import FetchResult, Opener, fetch, strip_query

# Base URL without the token.  Override the whole thing with EU_FSF_URL if the
# web gate ever changes the path or the parameter name.
EU_FSF_BASE_URL = (
    "https://webgate.ec.europa.eu/fsd/fsf/public/files/xmlFullSanctionsList_1_1/content"
)

TOKEN_ENV = "EU_FSF_TOKEN"
TOKEN_FILE_ENV = "EU_FSF_TOKEN_FILE"
URL_ENV = "EU_FSF_URL"

_PROGRESS_EVERY = 8 << 20  # log roughly every 8 MiB (the file is ~25 MiB)

# Back-compat alias: callers historically imported ``DownloadResult`` from here.
DownloadResult = FetchResult


class EuFsfTokenError(RuntimeError):
    """Raised when no EU FSF access token can be found."""


def redact(url: str) -> str:
    """Drop the query string (which carries the token) from ``url``."""
    return strip_query(url, note="token redacted")


def resolve_token(token: str | None = None) -> str:
    """Return the FSF token from (in order) the argument, a token file, the env.

    ``token`` passed in directly wins; then ``EU_FSF_TOKEN_FILE`` (a path whose
    contents are the token); then ``EU_FSF_TOKEN``.
    """
    if token:
        return token.strip()

    file_path = os.environ.get(TOKEN_FILE_ENV)
    if file_path:
        path = Path(file_path).expanduser()
        if not path.is_file():
            raise EuFsfTokenError(f"{TOKEN_FILE_ENV}={file_path!r} is not a readable file")
        return path.read_text(encoding="utf-8").strip()

    env_token = os.environ.get(TOKEN_ENV)
    if env_token and env_token.strip():
        return env_token.strip()

    raise EuFsfTokenError(
        "no EU FSF token found — set the EU_FSF_TOKEN environment variable, point "
        "EU_FSF_TOKEN_FILE at a file containing it, or pass --token-file. The token "
        "is the ?token=... value from the FSD web gate download link and must be "
        "treated as a secret (never commit it)."
    )


def resolve_url(*, token: str | None = None, url: str | None = None) -> str:
    """Build the full download URL, keeping the token out of everything logged."""
    url = url or os.environ.get(URL_ENV)
    if url:
        return url
    resolved = resolve_token(token)
    query = urllib.parse.urlencode({"token": resolved})
    return f"{EU_FSF_BASE_URL}?{query}"


def download_eu_fsf(
    *,
    token: str | None = None,
    url: str | None = None,
    timeout: float = 300.0,
    opener: Opener | None = None,
) -> FetchResult:
    """Fetch the full EU sanctions XML into memory.

    The returned provenance stores the *redacted* URL (the token stripped).
    """
    return fetch(
        resolve_url(token=token, url=url),
        timeout=timeout,
        redact=redact,
        progress_every=_PROGRESS_EVERY,
        opener=opener,
    )
