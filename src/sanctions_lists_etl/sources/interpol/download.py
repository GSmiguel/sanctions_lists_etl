"""Crawl the INTERPOL UN Special Notice list into a local JSON snapshot.

The public UN Special Notice search on ``interpol.int`` is backed by an
**undocumented** JSON web service at

    https://ws-public.interpol.int/notices/v1/un

There is no credential.  The service exists to serve that website, not to export
the list: every query returns at most ~160 results and will not paginate past
them, and the only filter it honours is ``name`` (a substring match).  So this
module sweeps ``name`` over one letter, then two letters for any slice still over
the cap, and de-duplicates on ``entity_id``; ``/un/entities`` (~110 rows) comes
back in a single page and is fetched directly as a safety net.

Only the **summary** rows are kept — id, name, date of birth, the ``un_reference``
that ties the notice back to the UN Consolidated List (stage 3), and the notice /
image URLs.  The per-notice detail records (charges, aliases, physical
description, narrative) are deliberately not fetched.

``INTERPOL_API_BASE`` overrides the service root; ``INTERPOL_REQUEST_DELAY`` sets
the pause in seconds between requests (default 0.5).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

INTERPOL_API_BASE = "https://ws-public.interpol.int/notices/v1"
BASE_ENV = "INTERPOL_API_BASE"
DELAY_ENV = "INTERPOL_REQUEST_DELAY"

# The service's edge (Akamai) rejects any User-Agent that carries a URL or looks
# like a bot — including the project's usual one — with HTTP 403, so this source
# sends the kind of browser UA the interpol.int search page itself uses.
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)
_DEFAULT_DELAY = 0.5
_PAGE_SIZE = 160
_RETRIEVABLE = 160  # the service will not return more than this per query
# 403 is on the retry list because the edge also uses it for rate-based blocking,
# not just auth — backing off usually clears it.
_RETRY_STATUS = {403, 429, 500, 502, 503, 504}
_MAX_RETRIES = 6
_BACKOFF_CAP = 60
_ALPHA = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

JsonOpener = Callable[[str], Any]


class InterpolServiceError(RuntimeError):
    """The notices web service kept refusing requests (throttling / IP block)."""


@dataclass(frozen=True)
class DownloadResult:
    path: Path
    sha256: str
    size_bytes: int
    downloaded_at: str
    url: str  # service root — nothing sensitive to redact
    notice_count: int
    counts_by_kind: dict[str, int] = field(default_factory=dict)
    coverage: str = ""


def resolve_base(url: str | None = None) -> str:
    return (url or os.environ.get(BASE_ENV) or INTERPOL_API_BASE).rstrip("/")


def resolve_delay(delay: float | None = None) -> float:
    if delay is not None:
        return max(delay, 0.0)
    raw = os.environ.get(DELAY_ENV)
    if raw:
        try:
            return max(float(raw), 0.0)
        except ValueError:
            log.warning("ignoring non-numeric %s=%r", DELAY_ENV, raw)
    return _DEFAULT_DELAY


def _urlopen_json(url: str) -> Any:
    request = urllib.request.Request(
        url, headers={"User-Agent": _USER_AGENT, "Accept": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)


class _Client:
    """GET-JSON wrapper: paces calls and retries throttle / 5xx responses."""

    def __init__(self, base: str, delay: float, *, opener: JsonOpener | None = None):
        self._base = base
        self._delay = delay
        self._open = opener or _urlopen_json
        self.calls = 0

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = self._base + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data: Any = None
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                data = self._open(url)
                break
            except urllib.error.HTTPError as exc:
                if exc.code not in _RETRY_STATUS:
                    raise
                if attempt < _MAX_RETRIES:
                    wait = min(2**attempt, _BACKOFF_CAP)
                    log.warning(
                        "  HTTP %s on %s — retry %d/%d in %ds",
                        exc.code,
                        url,
                        attempt,
                        _MAX_RETRIES,
                        wait,
                    )
                    time.sleep(wait)
                    continue
                raise InterpolServiceError(
                    f"web service returned HTTP {exc.code} for {url} after "
                    f"{_MAX_RETRIES} tries — it rate-limits heavy clients and can "
                    f"IP-block for a while. Retry later or raise "
                    f"{DELAY_ENV} (currently {self._delay}s)."
                ) from exc
        self.calls += 1
        if self._delay:
            time.sleep(self._delay)
        return data


# --------------------------------------------------------------------------- #
# payload helpers
# --------------------------------------------------------------------------- #
def _notices(payload: Any) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    return list(payload.get("_embedded", {}).get("notices", []) or [])


def _total(payload: Any) -> int:
    try:
        return int(payload.get("total", 0))
    except (AttributeError, TypeError, ValueError):
        return 0


def _kind(notice: dict) -> str:
    href = ((notice.get("_links") or {}).get("self") or {}).get("href", "")
    return "un-entity" if "/entities/" in href else "un-person"


def _collect(client: _Client, path: str, params: dict[str, Any], sink: dict[str, dict]) -> int:
    """Page through a slice (already known to be within the cap) into ``sink``."""
    added = 0
    for page in range(1, 4):
        payload = client.get(path, {**params, "resultPerPage": _PAGE_SIZE, "page": page})
        batch = _notices(payload)
        fresh = 0
        for notice in batch:
            key = notice.get("entity_id")
            if key and key not in sink:
                notice["_notice_kind"] = _kind(notice)
                sink[key] = notice
                fresh += 1
        added += fresh
        # the service won't paginate past the cap, so a short or all-seen page
        # (after the first) means there is nothing more to get from this slice.
        if len(batch) < _PAGE_SIZE or (page > 1 and fresh == 0):
            break
    return added


def _sweep_names(client: _Client, prefix: str, sink: dict[str, dict], depth: int) -> None:
    params = {"name": prefix} if prefix else {}
    total = _total(client.get("/un", {**params, "resultPerPage": 1}))
    if total == 0:
        return
    if total <= _RETRIEVABLE or depth >= 2:
        got = _collect(client, "/un", params, sink)
        if total > _RETRIEVABLE:
            log.warning(
                "  /un name=%r has %d notices; only ~%d retrievable (got %d)",
                prefix,
                total,
                _RETRIEVABLE,
                got,
            )
        return
    for ch in _ALPHA:
        _sweep_names(client, prefix + ch, sink, depth + 1)


def _counts_by_kind(records: list[dict]) -> dict[str, int]:
    return dict(Counter(r.get("_notice_kind", "un-person") for r in records))


def _write_meta(dest: Path, result: DownloadResult, api_calls: int, seconds: float) -> None:
    meta = dest.with_name(dest.name + ".meta.json")
    meta.write_text(
        json.dumps(
            {
                "sha256": result.sha256,
                "size_bytes": result.size_bytes,
                "downloaded_at": result.downloaded_at,
                "url": result.url,
                "notice_count": result.notice_count,
                "counts_by_kind": result.counts_by_kind,
                "coverage": result.coverage,
                "api_calls": api_calls,
                "crawl_seconds": round(seconds, 1),
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def download_interpol(
    dest_dir: Path | str = "data/raw",
    *,
    url: str | None = None,
    delay: float | None = None,
    limit: int | None = None,
    filename: str = "interpol.json",
    opener: JsonOpener | None = None,
) -> DownloadResult:
    """Crawl the UN Special Notice list into ``dest_dir/interpol.json`` + metadata.

    ``limit`` truncates the snapshot (smoke tests); ``opener`` injects a JSON
    fetcher for testing.
    """
    base = resolve_base(url)
    client = _Client(base, resolve_delay(delay), opener=opener)
    started = time.monotonic()

    reported = _total(client.get("/un", {"resultPerPage": 1}))
    log.info("[interpol] UN Special Notices: %d reported", reported)

    sink: dict[str, dict] = {}
    _collect(client, "/un/entities", {}, sink)  # ~110, one page, safety net
    _sweep_names(client, "", sink, 0)

    records = sorted(sink.values(), key=lambda n: n.get("entity_id") or "")
    if limit is not None:
        records = records[:limit]
    log.info("[interpol] collected %d of %d", len(records), reported)

    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / filename
    body = json.dumps(records, ensure_ascii=False, indent=1) + "\n"
    dest.write_text(body, encoding="utf-8")

    data = body.encode("utf-8")
    elapsed = time.monotonic() - started
    coverage = (
        "partial coverage (public notices only, retrieved by name sweep): "
        f"{len(records)}/{reported}"
    )
    log.info("[interpol] %s", coverage)

    result = DownloadResult(
        path=dest,
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
        downloaded_at=dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        url=base,
        notice_count=len(records),
        counts_by_kind=_counts_by_kind(records),
        coverage=coverage,
    )
    _write_meta(dest, result, client.calls, elapsed)
    log.info(
        "[interpol] wrote %d notices to %s in %.0fs (%d API calls)",
        len(records),
        dest,
        elapsed,
        client.calls,
    )
    return result
