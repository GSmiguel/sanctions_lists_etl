"""Tests for the INTERPOL crawler.

The web service caps every query at ~160 results and will not paginate past
them, so :mod:`sanctions_lists_etl.sources.interpol.download` partitions the
query space and de-duplicates.  ``_FakeService`` reproduces that behaviour
(including the ``/un`` endpoint ignoring its filters) over an in-memory dataset
so the partitioner can be exercised without touching the network.
"""

from __future__ import annotations

import json
import urllib.parse

import pytest

from sanctions_lists_etl.sources.interpol import download
from sanctions_lists_etl.sources.interpol.download import (
    INTERPOL_API_BASE,
    download_interpol,
    resolve_base,
    resolve_delay,
)
from sanctions_lists_etl.sources.interpol.parser import parse_interpol

_CAP = 160
_TODAY_YEAR = 2026


def _age(dob: str) -> int | None:
    if not dob or not dob[:4].isdigit():
        return None
    return _TODAY_YEAR - int(dob[:4])


class _FakeService:
    def __init__(self, red, un_persons, un_entities):
        self._red = red
        self._un_persons = un_persons
        self._un_entities = un_entities
        self._by_id = {n["entity_id"]: n for n in red + un_persons + un_entities}
        self.calls = 0

    # the injected opener
    def __call__(self, url: str):
        self.calls += 1
        path, _, query = url.partition("?")
        path = path.split("/notices/v1", 1)[1]
        params = {k: v[0] for k, v in urllib.parse.parse_qs(query).items()}

        parts = path.strip("/").split("/")
        if len(parts) >= 2 and parts[-1] not in ("persons", "entities"):
            return self._by_id[parts[-1].replace("-", "/")]

        if path.startswith("/red"):
            pool = [n for n in self._red if self._red_match(n, params)]
        elif path.startswith("/un/entities"):
            pool = list(self._un_entities)
        elif path.startswith("/un/persons"):
            # the real endpoint honours only `name`
            name = params.get("name", "").upper()
            pool = [n for n in self._un_persons if name in n["name"].upper()]
        else:
            raise AssertionError(f"unexpected path {path!r}")

        rpp = int(params.get("resultPerPage", 20))
        page = int(params.get("page", 1))
        offset = (page - 1) * rpp
        window = [] if offset >= _CAP else pool[offset : min(offset + rpp, _CAP)]
        return {
            "total": len(pool),
            "_embedded": {"notices": [_summary(n) for n in window]},
            "_links": {},
        }

    @staticmethod
    def _red_match(notice, params):
        if "nationality" in params and params["nationality"] not in notice.get("nationalities", []):
            return False
        if "sexId" in params and params["sexId"] != notice.get("sex_id"):
            return False
        if "forename" in params and not notice["forename"].upper().startswith(params["forename"].upper()):
            return False
        age = _age(notice.get("date_of_birth", ""))
        if "ageMin" in params and (age is None or age < int(params["ageMin"])):
            return False
        if "ageMax" in params and (age is None or age > int(params["ageMax"])):
            return False
        return True


def _summary(notice: dict) -> dict:
    keep = ("entity_id", "name", "forename", "date_of_birth", "nationalities", "un_reference")
    out = {k: notice[k] for k in keep if k in notice}
    kind = notice["_kind"]
    stem = "un/persons" if kind == "un-person" else "un/entities" if kind == "un-entity" else "red"
    out["_links"] = {
        "self": {"href": f"https://ws-public.interpol.int/notices/v1/{stem}/{notice['entity_id'].replace('/', '-')}"}
    }
    return out


def _make_dataset():
    red = []
    for i in range(120):
        red.append(_red(f"2020/RUM{i:03d}", "RU", "M", f"IVAN{i}", "1985/01/01"))
    for i in range(80):
        red.append(_red(f"2020/RUF{i:03d}", "RU", "F", f"OLGA{i}", "1990/01/01"))
    for i in range(50):
        red.append(_red(f"2021/US{i:03d}", "US", "M", f"JOHN{i}", "1978/01/01"))
    for i in range(30):
        red.append(_red(f"2021/BR{i:03d}", "BR", "F", f"MARIA{i}", "1995/01/01"))
    # no listed nationality — only reachable via the forename sweep
    for i in range(5):
        red.append(_red(f"2022/NUL{i:03d}", None, "M", f"QNULL{i}", "1988/01/01"))

    un_persons = []
    for i in range(100):
        un_persons.append(_un_person(f"2015/ALP{i:03d}", f"ALPHA{i}", f"AA{i}", "QDi.1"))
    for i in range(100):
        un_persons.append(_un_person(f"2016/BET{i:03d}", f"BETA{i}", f"BB{i}", "QDi.2"))

    un_entities = [
        _un_entity("2011/E01", "FIRST FOUNDATION", "QDe.001"),
        _un_entity("2011/E02", "SECOND GROUP", "QDe.002"),
        _un_entity("2011/E03", "THIRD NETWORK", "QDe.003"),
    ]
    return red, un_persons, un_entities


def _red(entity_id, nationality, sex, forename, dob):
    return {
        "_kind": "red",
        "entity_id": entity_id,
        "name": "DOE",
        "forename": forename,
        "date_of_birth": dob,
        "sex_id": sex,
        "nationalities": [nationality] if nationality else [],
        "place_of_birth": "SOMEWHERE",  # detail-only field, proves enrichment ran
    }


def _un_person(entity_id, name, forename, ref):
    return {
        "_kind": "un-person",
        "entity_id": entity_id,
        "name": name,
        "forename": forename,
        "date_of_birth": "1970/01/01",
        "un_reference": ref,
        "nationalities": ["IQ"],
        "summary": "listed",
    }


def _un_entity(entity_id, name, ref):
    return {"_kind": "un-entity", "entity_id": entity_id, "name": name, "un_reference": ref, "summary": "listed"}


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


def test_crawl_partitions_past_the_cap_and_dedupes(tmp_path):
    red, un_persons, un_entities = _make_dataset()
    service = _FakeService(red, un_persons, un_entities)

    result = download_interpol(tmp_path, delay=0, opener=service)

    snapshot = json.loads(result.path.read_text())
    ids = {n["entity_id"] for n in snapshot}

    # every Red Notice, including the 5 with no nationality and both 200-strong
    # slices that individually blow past the 160 cap
    assert len({i for i in ids if i.startswith(("2020/", "2021/", "2022/"))}) == 285
    assert {f"2022/NUL{i:03d}" for i in range(5)} <= ids
    # every UN Special Notice (persons via the name-substring sweep, entities whole)
    assert len({i for i in ids if i.startswith(("2015/", "2016/"))}) == 200
    assert len({i for i in ids if i.startswith("2011/")}) == 3
    assert len(snapshot) == 488

    # enrichment merged the detail-only field onto every record
    assert all(n.get("place_of_birth") == "SOMEWHERE" for n in snapshot if n["_notice_kind"] == "red")
    assert result.notice_count == 488
    assert result.counts_by_kind == {"red": 285, "un-person": 200, "un-entity": 3}
    assert "Red Notices 285/285" in result.coverage


def test_meta_sidecar_is_written(tmp_path):
    red, un_persons, un_entities = _make_dataset()
    service = _FakeService(red, un_persons, un_entities)
    result = download_interpol(tmp_path, delay=0, opener=service, un=False)

    meta = json.loads((result.path.with_name(result.path.name + ".meta.json")).read_text())
    assert meta["sha256"] == result.sha256
    assert meta["notice_count"] == result.notice_count
    assert meta["counts_by_kind"] == {"red": 285}
    assert meta["api_calls"] > 0
    assert "UN Special Notices" not in result.coverage


def test_limit_caps_enrichment(tmp_path):
    red, un_persons, un_entities = _make_dataset()
    service = _FakeService(red, un_persons, un_entities)
    result = download_interpol(tmp_path, delay=0, opener=service, un=False, limit=10)
    assert result.notice_count == 10


def test_snapshot_is_parseable(tmp_path):
    red, un_persons, un_entities = _make_dataset()
    service = _FakeService(red, un_persons, un_entities)
    result = download_interpol(tmp_path, delay=0, opener=service)
    records = parse_interpol(result.path)
    assert len(records) == 488
    assert {r.notice_type for r in records} == {"Red Notice", "UN Special Notice"}
