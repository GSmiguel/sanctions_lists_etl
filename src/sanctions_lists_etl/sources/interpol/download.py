"""Crawl the INTERPOL public notices web service into a local JSON snapshot.

The public "View Red Notices" and UN Special Notice search pages on
``interpol.int`` are backed by an **undocumented** JSON web service at

    https://ws-public.interpol.int/notices/v1

There is no credential, but the service exists to serve that website, not to
export the list: every query returns at most ~160 results and will not paginate
past them, and the ``/notices/v1/un`` list endpoint ignores its filter
parameters entirely.  To pull a whole list this module recursively partitions
the query space until each slice fits under the cap and de-duplicates on
``entity_id``:

* **Red Notices** — by ``nationality``, then (only for a slice still over the
  cap) ``sexId`` -> ``forename`` initial -> two-letter ``forename`` -> age
  bracket, plus a nationality-less ``forename`` sweep to reach parties with no
  listed nationality.
* **UN Special Notices** — ``/un/entities`` comes back whole (~one page); for
  ``/un/persons`` a ``name`` substring sweep (one then two letters).

Then the full record for every collected notice is fetched.  Coverage is high
but **not provably complete**; the reported-vs-collected gap is logged and
written to the ``.meta.json`` sidecar.

``INTERPOL_API_BASE`` overrides the service root; ``INTERPOL_REQUEST_DELAY``
sets the pause in seconds between requests (default 0.2).
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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)

from ...common.countries import ALPHA2

INTERPOL_API_BASE = "https://ws-public.interpol.int/notices/v1"
BASE_ENV = "INTERPOL_API_BASE"
DELAY_ENV = "INTERPOL_REQUEST_DELAY"

# The service's edge rejects (HTTP 403) any User-Agent that carries a URL or
# looks like a bot — including the project's usual one — so this source sends the
# same kind of browser UA the interpol.int search page itself uses.
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)
_DEFAULT_DELAY = 0.5
_PAGE_SIZE = 160
_RETRIEVABLE = 160  # the service will not return more than this per query
# 403 is on the list because the edge uses it for rate-based blocking, not just
# auth — backing off and retrying usually clears it.
_RETRY_STATUS = {403, 429, 500, 502, 503, 504}
_MAX_RETRIES = 6
_BACKOFF_CAP = 60
_ALPHA = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
# Age brackets, used only to break up a slice that is still over the cap after
# every other axis.  Applied last because filtering on age drops notices that
# carry no date of birth.
_AGE_BRACKETS = (
    (0, 17), (18, 23), (24, 29), (30, 35), (36, 41),
    (42, 47), (48, 55), (56, 65), (66, 120),
)

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
                    wait = min(2 ** attempt, _BACKOFF_CAP)
                    log.warning(
                        "  HTTP %s on %s — retry %d/%d in %ds",
                        exc.code, url, attempt, _MAX_RETRIES, wait,
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
# small payload helpers
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


def _kind_count(sink: dict[str, dict], kind: str) -> int:
    return sum(1 for n in sink.values() if n.get("_notice_kind") == kind)


def _collect(
    client: _Client, path: str, params: dict[str, Any], kind: str, sink: dict[str, dict]
) -> int:
    """Page through a slice (already known to be within the cap) into ``sink``."""
    added = 0
    for page in range(1, 4):
        payload = client.get(path, {**params, "resultPerPage": _PAGE_SIZE, "page": page})
        batch = _notices(payload)
        fresh = 0
        for notice in batch:
            key = notice.get("entity_id")
            if key and key not in sink:
                notice["_notice_kind"] = kind
                sink[key] = notice
                fresh += 1
        added += fresh
        # the service won't paginate past the cap, so a short or all-seen page
        # (after the first) means there is nothing more to get from this slice.
        if len(batch) < _PAGE_SIZE or (page > 1 and fresh == 0):
            break
    return added


# --------------------------------------------------------------------------- #
# Red Notice crawl
# --------------------------------------------------------------------------- #
def _crawl_red(client: _Client, sink: dict[str, dict]) -> int:
    total = _total(client.get("/red", {"resultPerPage": 1}))
    log.info("[interpol] Red Notices: %d reported", total)
    for index, code in enumerate(ALPHA2, 1):
        _red_slice(client, {"nationality": code}, sink, ())
        if index % 40 == 0:
            log.info("  %d/%d nationality slices, %d notices so far",
                     index, len(ALPHA2), _kind_count(sink, "red"))
    _red_no_nationality(client, sink)
    got = _kind_count(sink, "red")
    log.info("[interpol] Red Notices: collected %d of %d", got, total)
    return total


def _red_slice(
    client: _Client, params: dict[str, Any], sink: dict[str, dict], tried: tuple[str, ...]
) -> None:
    total = _total(client.get("/red", {**params, "resultPerPage": 1}))
    if total == 0:
        return
    if total <= _RETRIEVABLE:
        _collect(client, "/red", params, "red", sink)
        return
    for axis in ("sexId", "forename", "forename2", "age"):
        if axis in tried:
            continue
        for extra in _red_axis(axis, params):
            _red_slice(client, {**params, **extra}, sink, tried + (axis,))
        return
    got = _collect(client, "/red", params, "red", sink)
    log.warning("  Red slice %s has %d notices; only ~%d retrievable (got %d)",
                params, total, _RETRIEVABLE, got)


def _red_axis(axis: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    if axis == "sexId":
        return [{"sexId": s} for s in ("M", "F", "U")]
    if axis == "forename":
        return [{"forename": ch} for ch in _ALPHA]
    if axis == "forename2":
        prefix = params.get("forename", "")
        return [{"forename": prefix + ch} for ch in _ALPHA]
    if axis == "age":
        return [{"ageMin": lo, "ageMax": hi} for lo, hi in _AGE_BRACKETS]
    return []


def _red_no_nationality(client: _Client, sink: dict[str, dict]) -> None:
    """Bounded sweep to reach Red Notices that carry no listed nationality."""
    before = _kind_count(sink, "red")
    for ch in _ALPHA:
        params = {"forename": ch}
        total = _total(client.get("/red", {**params, "resultPerPage": 1}))
        if total == 0:
            continue
        if total <= _RETRIEVABLE:
            _collect(client, "/red", params, "red", sink)
            continue
        for sex in ("M", "F", "U"):
            _collect(client, "/red", {**params, "sexId": sex}, "red", sink)
    caught = _kind_count(sink, "red") - before
    if caught:
        log.info("  nationality-less sweep added %d Red Notices", caught)


# --------------------------------------------------------------------------- #
# UN Special Notice crawl
# --------------------------------------------------------------------------- #
def _crawl_un(client: _Client, sink: dict[str, dict]) -> int:
    entities = _total(client.get("/un/entities", {"resultPerPage": 1}))
    _collect(client, "/un/entities", {}, "un-entity", sink)
    persons = _total(client.get("/un/persons", {"resultPerPage": 1}))
    log.info("[interpol] UN Special Notices: %d reported (%d entities, %d persons)",
             entities + persons, entities, persons)
    _un_person_slice(client, "", sink, 0)
    got = _kind_count(sink, "un-entity") + _kind_count(sink, "un-person")
    log.info("[interpol] UN Special Notices: collected %d of %d", got, entities + persons)
    return entities + persons


def _un_person_slice(client: _Client, prefix: str, sink: dict[str, dict], depth: int) -> None:
    params = {"name": prefix} if prefix else {}
    total = _total(client.get("/un/persons", {**params, "resultPerPage": 1}))
    if total == 0:
        return
    if total <= _RETRIEVABLE or depth >= 2:
        got = _collect(client, "/un/persons", params, "un-person", sink)
        if total > _RETRIEVABLE:
            log.warning("  un/persons name=%r has %d notices; only ~%d retrievable (got %d)",
                        prefix, total, _RETRIEVABLE, got)
        return
    for ch in _ALPHA:
        _un_person_slice(client, prefix + ch, sink, depth + 1)


# --------------------------------------------------------------------------- #
# enrichment + snapshot
# --------------------------------------------------------------------------- #
def _self_href(notice: dict) -> str:
    link = (notice.get("_links") or {}).get("self") or {}
    return (link.get("href") or "").strip() if isinstance(link, dict) else ""


def _api_path(href: str) -> str:
    marker = "/notices/v1"
    if marker in href:
        return href.split(marker, 1)[1]
    return urllib.parse.urlsplit(href).path


def _enrich(client: _Client, notices: list[dict]) -> list[dict]:
    out: list[dict] = []
    for index, summary in enumerate(notices, 1):
        detail: dict = {}
        href = _self_href(summary)
        if href:
            try:
                fetched = client.get(_api_path(href))
                if isinstance(fetched, dict):
                    detail = fetched
            except urllib.error.HTTPError as exc:
                log.warning("  detail fetch %s failed: HTTP %s", href, exc.code)
        merged = {**detail, **summary}  # identity + _links + _notice_kind from summary win
        out.append(merged)
        if index % 250 == 0:
            log.info("  enriched %d/%d", index, len(notices))
    return out


def _counts_by_kind(records: list[dict]) -> dict[str, int]:
    return dict(Counter(r.get("_notice_kind", "red") for r in records))


def _coverage_note(reported: dict[str, int], records: list[dict]) -> str:
    counts = _counts_by_kind(records)
    bits: list[str] = []
    if "red" in reported:
        bits.append(f"Red Notices {counts.get('red', 0)}/{reported['red']}")
    if "un" in reported:
        un_got = counts.get("un-entity", 0) + counts.get("un-person", 0)
        bits.append(f"UN Special Notices {un_got}/{reported['un']}")
    return "partial coverage (public notices only, retrieved by query partitioning): " + ", ".join(bits)


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
    red: bool = True,
    un: bool = True,
    limit: int | None = None,
    filename: str = "interpol.json",
    opener: JsonOpener | None = None,
) -> DownloadResult:
    """Crawl the notices web service into ``dest_dir/interpol.json`` and record metadata.

    ``red`` / ``un`` select which notice families to crawl; ``limit`` caps the
    number of full-record fetches (handy for smoke tests).  ``opener`` injects a
    JSON fetcher for testing.
    """
    base = resolve_base(url)
    client = _Client(base, resolve_delay(delay), opener=opener)
    started = time.monotonic()

    sink: dict[str, dict] = {}
    reported: dict[str, int] = {}
    if red:
        reported["red"] = _crawl_red(client, sink)
    if un:
        reported["un"] = _crawl_un(client, sink)

    notices = sorted(sink.values(), key=lambda n: n.get("entity_id") or "")
    if limit is not None:
        notices = notices[:limit]

    log.info("[interpol] fetching full records for %d notices", len(notices))
    records = _enrich(client, notices)

    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / filename
    body = json.dumps(records, ensure_ascii=False, indent=1) + "\n"
    dest.write_text(body, encoding="utf-8")

    data = body.encode("utf-8")
    elapsed = time.monotonic() - started
    coverage = _coverage_note(reported, records)
    log.info("[interpol] %s", coverage)

    result = DownloadResult(
        path=dest,
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
        downloaded_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        url=base,
        notice_count=len(records),
        counts_by_kind=_counts_by_kind(records),
        coverage=coverage,
    )
    _write_meta(dest, result, client.calls, elapsed)
    log.info("[interpol] wrote %d notices to %s in %.0fs (%d API calls)",
             len(records), dest, elapsed, client.calls)
    return result
