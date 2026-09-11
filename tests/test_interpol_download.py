"""Tests for the INTERPOL UN Special Notice crawler.

The web service caps every query at ~160 results, won't paginate past them, and
honours only the ``name`` filter (a substring match).  ``_FakeService``
reproduces that over an in-memory dataset so the name sweep can be exercised
without touching the network.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse

import pytest

from sanctions_lists_etl.sources.interpol import download
from sanctions_lists_etl.sources.interpol.download import (
    INTERPOL_API_BASE,
    InterpolServiceError,
    download_interpol,
    resolve_base,
    resolve_delay,
)
from sanctions_lists_etl.sources.interpol.parser import parse_interpol

_CAP = 160


class _FakeService:
    def __init__(self, notices):
        self._notices = notices
        self.calls = 0

    def __call__(self, url: str):  # the injected opener
        self.calls += 1
        path, _, query = url.partition("?")
        path = path.split("/notices/v1", 1)[1]
        params = {k: v[0] for k, v in urllib.parse.parse_qs(query).items()}

        if path.startswith("/un/entities"):
            pool = [n for n in self._notices if n["_kind"] == "un-entity"]
        elif path.startswith("/un"):
            name = params.get("name", "").upper()
            pool = [n for n in self._notices if name in n["name"].upper()]
        else:
            raise AssertionError(f"unexpected path {path!r}")

        rpp = int(params.get("resultPerPage", 20))
        page = int(params.get("page", 1))
        offset = (page - 1) * rpp
        window = [] if offset >= _CAP else pool[offset : min(offset + rpp, _CAP)]
        return {
            "total": len(pool),
            "_embedded": {"notices": [_row(n) for n in window]},
            "_links": {},
        }


def _row(notice: dict) -> dict:
    stem = "un/entities" if notice["_kind"] == "un-entity" else "un/persons"
    slug = notice["entity_id"].replace("/", "-")
    row = {
        "entity_id": notice["entity_id"],
        "name": notice["name"],
        "un_reference": notice["un_reference"],
        "_links": {"self": {"href": f"https://ws-public.interpol.int/notices/v1/{stem}/{slug}"}},
    }
    if notice["_kind"] == "un-person":
        row["forename"] = notice.get("forename", "")
        row["date_of_birth"] = notice.get("date_of_birth", "")
    return row


def _make_dataset():
    notices = []
    for i in range(100):
        notices.append(_person(f"2015/ALP{i:03d}", f"ALPHA{i}", f"QDi.{i}"))
    for i in range(100):
        notices.append(_person(f"2016/BET{i:03d}", f"BETA{i}", f"SDi.{i}"))
    for i in range(50):
        notices.append(_entity(f"2011/GAM{i:03d}", f"GAMMA{i} FOUNDATION", f"QDe.{i:03d}"))
    return notices


def _person(entity_id, name, ref):
    return {
        "_kind": "un-person",
        "entity_id": entity_id,
        "name": name,
        "forename": "TEST",
        "date_of_birth": "1970/01/01",
        "un_reference": ref,
    }


def _entity(entity_id, name, ref):
    return {"_kind": "un-entity", "entity_id": entity_id, "name": name, "un_reference": ref}


# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv("INTERPOL_API_BASE", raising=False)
    monkeypatch.delenv("INTERPOL_REQUEST_DELAY", raising=False)


def test_resolve_base_default_env_and_arg(monkeypatch):
    assert resolve_base() == INTERPOL_API_BASE
    assert resolve_base("https://example.test/v1/") == "https://example.test/v1"
    monkeypatch.setenv("INTERPOL_API_BASE", "https://env.test/v1")
    assert resolve_base() == "https://env.test/v1"


def test_resolve_delay(monkeypatch):
    assert resolve_delay() == pytest.approx(0.5)
    assert resolve_delay(0) == 0
    monkeypatch.setenv("INTERPOL_REQUEST_DELAY", "1.5")
    assert resolve_delay() == pytest.approx(1.5)
    monkeypatch.setenv("INTERPOL_REQUEST_DELAY", "nope")
    assert resolve_delay() == pytest.approx(0.5)


def test_name_sweep_covers_everything_and_dedupes(tmp_path):
    service = _FakeService(_make_dataset())
    result = download_interpol(tmp_path, delay=0, opener=service)

    snapshot = json.loads(result.path.read_text())
    ids = {n["entity_id"] for n in snapshot}
    # both 100-strong person groups (each individually over the 160 cap under a
    # one-letter name) and every entity, once each
    assert len(snapshot) == 250
    assert len({i for i in ids if i.startswith("2015/")}) == 100
    assert len({i for i in ids if i.startswith("2016/")}) == 100
    assert len({i for i in ids if i.startswith("2011/")}) == 50

    kinds = {n["entity_id"]: n["_notice_kind"] for n in snapshot}
    assert kinds["2015/ALP000"] == "un-person"
    assert kinds["2011/GAM000"] == "un-entity"
    assert result.counts_by_kind == {"un-person": 200, "un-entity": 50}
    assert result.coverage == (
        "partial coverage (public notices only, retrieved by name sweep): 250/250"
    )


def test_meta_sidecar_is_written(tmp_path):
    service = _FakeService(_make_dataset())
    result = download_interpol(tmp_path, delay=0, opener=service)

    meta = json.loads((result.path.with_name(result.path.name + ".meta.json")).read_text())
    assert meta["sha256"] == result.sha256
    assert meta["notice_count"] == 250
    assert meta["counts_by_kind"] == {"un-person": 200, "un-entity": 50}
    assert meta["api_calls"] > 0


def test_limit_truncates_the_snapshot(tmp_path):
    service = _FakeService(_make_dataset())
    result = download_interpol(tmp_path, delay=0, opener=service, limit=10)
    assert result.notice_count == 10


def test_persistent_http_error_becomes_a_clean_runtime_error(tmp_path, monkeypatch):
    monkeypatch.setattr(download.time, "sleep", lambda _: None)

    def blocked(url):
        raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)

    with pytest.raises(InterpolServiceError, match="HTTP 403"):
        download_interpol(tmp_path, delay=0, opener=blocked)


def test_snapshot_is_parseable(tmp_path):
    service = _FakeService(_make_dataset())
    result = download_interpol(tmp_path, delay=0, opener=service)
    records = parse_interpol(result.path)
    assert len(records) == 250
    assert {r.notice_type for r in records} == {"UN Special Notice"}
    assert {r.party_type for r in records} == {"Individual", "Entity"}
    assert all(r.un_reference for r in records)
