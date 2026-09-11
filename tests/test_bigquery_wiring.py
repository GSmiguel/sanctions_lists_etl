"""Each pipeline's ``bigquery=`` kwarg calls (or skips) common.sinks.bigquery.load_bigquery.

Patches ``load_bigquery`` where each pipeline imported it (not the source
module) — the standard "patch where it's used" rule — so this needs no real
BigQuery client and runs regardless of whether the optional extra is installed.
"""

from __future__ import annotations

from sanctions_lists_etl.sources.eu import pipeline as eu_pipeline
from sanctions_lists_etl.sources.ofac import pipeline as ofac_pipeline
from sanctions_lists_etl.sources.uk import pipeline as uk_pipeline
from sanctions_lists_etl.sources.un import pipeline as un_pipeline


def _spy(monkeypatch, module):
    calls: list[dict] = []

    def fake_load_bigquery(build, to_normalized, *, source_key, project, dataset=None, **_):
        calls.append({"source_key": source_key, "project": project, "dataset": dataset})
        build.metadata["bigquery"] = "loaded (spy)"

    monkeypatch.setattr(module, "load_bigquery", fake_load_bigquery)
    return calls


def test_un_run_calls_load_bigquery_when_enabled(sample_un_xml, tmp_path, monkeypatch):
    calls = _spy(monkeypatch, un_pipeline)
    result = un_pipeline.run(
        output_dir=tmp_path,
        raw_dir=tmp_path,
        xml_path=sample_un_xml,
        download=False,
        bigquery=True,
        bq_project="proj",
    )
    assert calls == [{"source_key": "un_sc", "project": "proj", "dataset": None}]
    assert result.metadata["bigquery"] == "loaded (spy)"


def test_un_run_skips_load_bigquery_when_disabled(sample_un_xml, tmp_path, monkeypatch):
    calls = _spy(monkeypatch, un_pipeline)
    un_pipeline.run(output_dir=tmp_path, raw_dir=tmp_path, xml_path=sample_un_xml, download=False)
    assert calls == []


def test_eu_run_calls_load_bigquery_when_enabled(sample_eu_xml, tmp_path, monkeypatch):
    calls = _spy(monkeypatch, eu_pipeline)
    eu_pipeline.run(
        output_dir=tmp_path,
        raw_dir=tmp_path,
        xml_path=sample_eu_xml,
        download=False,
        bigquery=True,
        bq_project="proj",
    )
    assert calls == [{"source_key": "eu_fsf", "project": "proj", "dataset": None}]


def test_uk_run_calls_load_bigquery_when_enabled(sample_uk_xml, tmp_path, monkeypatch):
    calls = _spy(monkeypatch, uk_pipeline)
    uk_pipeline.run(
        output_dir=tmp_path,
        raw_dir=tmp_path,
        xml_path=sample_uk_xml,
        download=False,
        bigquery=True,
        bq_project="proj",
    )
    assert calls == [{"source_key": "uk_fcdo", "project": "proj", "dataset": None}]


def test_ofac_run_calls_load_bigquery_once_per_list(sample_xml, tmp_path, monkeypatch):
    calls = _spy(monkeypatch, ofac_pipeline)
    result = ofac_pipeline.run(
        output_dir=tmp_path,
        raw_dir=tmp_path,
        xml_path=sample_xml,
        download=False,
        bigquery=True,
        bq_project="proj",
    )
    # a local --xml is always treated as the sdn list only (see run()'s docstring)
    assert calls == [{"source_key": "ofac_sdn", "project": "proj", "dataset": None}]
    assert result.metadata["sdn_bigquery"] == "loaded (spy)"
