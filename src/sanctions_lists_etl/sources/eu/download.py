"""Download the EU consolidated financial sanctions list (FSF full XML).

The EU FSD web gate exposes a bot/crawler download at

    https://webgate.ec.europa.eu/fsd/fsf/public/files/xmlFullSanctionsList_1_1/content?token=<TOKEN>

The ``token`` query parameter is a **credential**: it authenticates the request
in place of a normal login, so it must never be committed to the repository or
written into a build artifact.  This module only ever reads it from the
environment (``EU_FSF_TOKEN``) or a file pointed at by ``EU_FSF_TOKEN_FILE`` /
``--token-file``, and every log line and metadata sidecar stores the URL with
the query string stripped.
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

# Base URL without the token.  Override the whole thing with EU_FSF_URL if the
# web gate ever changes the path or the parameter name.
EU_FSF_BASE_URL = (
    "https://webgate.ec.europa.eu/fsd/fsf/public/files/xmlFullSanctionsList_1_1/content"
)

TOKEN_ENV = "EU_FSF_TOKEN"
TOKEN_FILE_ENV = "EU_FSF_TOKEN_FILE"
URL_ENV = "EU_FSF_URL"

_USER_AGENT = "sanctions-lists-etl/0.1 (+https://github.com/GSmiguel/sanctions_lists_etl)"
_CHUNK = 1 << 20
_PROGRESS_EVERY = 8 << 20  # log roughly every 8 MiB (the file is ~25 MiB)


class EuFsfTokenError(RuntimeError):
    """Raised when no EU FSF access token can be found."""


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
    """Drop the query string (which carries the token) from ``url``."""
    split = urllib.parse.urlsplit(url)
    clean = urllib.parse.urlunsplit((split.scheme, split.netloc, split.path, "", ""))
    return f"{clean} (token redacted)" if split.query else clean


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
    dest_dir: Path | str = "data/raw",
    *,
    token: str | None = None,
    url: str | None = None,
    filename: str = "eu_fsf_full.xml",
    timeout: float = 300.0,
) -> DownloadResult:
    """Fetch the full EU sanctions XML into ``dest_dir`` and record its metadata.

    A sibling ``<filename>.meta.json`` captures the checksum, size and timestamp
    (and the *redacted* URL) so later stages can tell which snapshot they used.
    """
    full_url = resolve_url(token=token, url=url)
    safe_url = redact(full_url)

    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / filename
    tmp = dest.with_suffix(dest.suffix + ".part")

    request = urllib.request.Request(full_url, headers={"User-Agent": _USER_AGENT})
    hasher = hashlib.sha256()
    size = 0
    started = time.monotonic()
    log.info("downloading %s", safe_url)
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
        downloaded_at=dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        url=safe_url,
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
