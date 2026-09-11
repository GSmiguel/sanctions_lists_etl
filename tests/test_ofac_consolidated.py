"""The OFAC Consolidated (Non-SDN) list rides on the same parser and columns as
the SDN list; only the download URL and BigQuery source key differ."""

import pytest

from sanctions_lists_etl.cli import build_parser
from sanctions_lists_etl.runner import run_source
from sanctions_lists_etl.sources.ofac import pipeline as ofac_pipeline
from sanctions_lists_etl.sources.ofac.download import FetchResult
from sanctions_lists_etl.sources.ofac.pipeline import options_from_args


def _stub_download(monkeypatch, sample_xml):
    """Every requested list downloads to the same fixture content.

    There is no on-disk cache any more, so exercising both lists without
    ``--xml`` (which only ever implies the SDN list) means stubbing the
    module-level ``download_advanced_xml`` the pipeline calls.
    """
    content = sample_xml.read_bytes()

    def _fake(*, url, timeout=300.0, opener=None):
        return FetchResult(content, "deadbeef", len(content), "2026-01-01T00:00:00+00:00", url)

    monkeypatch.setattr(ofac_pipeline, "download_advanced_xml", _fake)


def test_consolidated_run_parses_its_own_list(sample_xml, monkeypatch):
    _stub_download(monkeypatch, sample_xml)

    result = run_source("ofac", lists=("consolidated",))

    assert result.record_count == 4
    assert result.metadata["lists_built"] == "consolidated"


def test_both_lists_produce_combined_counts(sample_xml, monkeypatch):
    _stub_download(monkeypatch, sample_xml)

    result = run_source("ofac", lists=("sdn", "consolidated"))

    assert result.record_count == 8  # 4 + 4
    assert result.metadata["sdn_record_count"] == "4"
    assert result.metadata["consolidated_record_count"] == "4"


@pytest.mark.parametrize(
    "argv, expected",
    [
        (["ofac"], ("sdn", "consolidated")),
        (["ofac", "--list", "sdn"], ("sdn",)),
        (["ofac", "--list", "consolidated"], ("consolidated",)),
        (["ofac", "--list", "both"], ("sdn", "consolidated")),
    ],
)
def test_list_flag_maps_to_lists_option(argv, expected):
    args = build_parser().parse_args(argv)
    assert options_from_args(args)["lists"] == expected
