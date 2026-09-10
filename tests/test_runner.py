import pytest
from openpyxl import load_workbook

from sanctions_lists_etl import available_sources, run_source
from sanctions_lists_etl import runner
from sanctions_lists_etl.base import Source, SourceResult
from sanctions_lists_etl.cli import main


def test_sources_are_registered():
    assert {"ofac", "eu", "un", "interpol"} <= set(available_sources())


def test_run_source_end_to_end(sample_xml, tmp_path):
    result = run_source(
        "ofac",
        output_dir=tmp_path,
        raw_dir=tmp_path,
        xml_path=sample_xml,
        download=False,
    )
    assert result.source == "ofac"
    assert result.record_count == 4
    assert result.xlsx_path.exists()
    assert load_workbook(result.xlsx_path)["SDN"].max_row == 5


def test_run_eu_source_end_to_end(sample_eu_xml, tmp_path):
    result = run_source(
        "eu",
        output_dir=tmp_path,
        raw_dir=tmp_path,
        xml_path=sample_eu_xml,
        download=False,
    )
    assert result.source == "eu"
    assert result.record_count == 5
    assert result.xlsx_path.exists()
    assert load_workbook(result.xlsx_path)["EU"].max_row == 6


def test_run_un_source_end_to_end(sample_un_xml, tmp_path):
    result = run_source(
        "un",
        output_dir=tmp_path,
        raw_dir=tmp_path,
        xml_path=sample_un_xml,
        download=False,
    )
    assert result.source == "un"
    assert result.record_count == 7
    assert result.counts_by_type == {"Individual": 4, "Entity": 3}
    assert result.xlsx_path.exists()
    assert load_workbook(result.xlsx_path)["UN"].max_row == 8


def test_run_interpol_source_end_to_end(sample_interpol_json, tmp_path):
    result = run_source(
        "interpol",
        output_dir=tmp_path,
        raw_dir=tmp_path,
        json_path=sample_interpol_json,
        download=False,
    )
    assert result.source == "interpol"
    assert result.record_count == 6
    assert result.counts_by_type == {"Individual": 4, "Entity": 2}
    assert result.xlsx_path.exists()
    assert load_workbook(result.xlsx_path)["INTERPOL"].max_row == 7


def test_cli_eu_requires_token_without_xml(tmp_path, capsys, monkeypatch):
    for name in ("EU_FSF_TOKEN", "EU_FSF_TOKEN_FILE", "EU_FSF_URL"):
        monkeypatch.delenv(name, raising=False)
    exit_code = main(
        ["--output-dir", str(tmp_path), "--raw-dir", str(tmp_path), "eu", "--no-download"]
    )
    assert exit_code == 1
    assert "EU_FSF_TOKEN" in capsys.readouterr().err


def test_cli_runs_single_source(sample_xml, tmp_path, capsys):
    exit_code = main(
        [
            "--output-dir",
            str(tmp_path),
            "--raw-dir",
            str(tmp_path),
            "ofac",
            "--xml",
            str(sample_xml),
            "--individuals-entities-only",
        ]
    )
    assert exit_code == 0
    assert (tmp_path / "ofac_sdn.xlsx").exists()
    out = capsys.readouterr().out
    assert "[ofac]" in out
    assert "Vessel" not in out


def test_cli_list(capsys):
    assert main(["--list"]) == 0
    assert "ofac" in capsys.readouterr().out


def test_run_all_keeps_going_past_a_failing_source(monkeypatch, tmp_path):
    def ok_run(*, output_dir, raw_dir, **_):
        return SourceResult(source="ok", xlsx_path=tmp_path / "ok.xlsx", record_count=1)

    def boom_run(*, output_dir, raw_dir, **_):
        raise RuntimeError("no credential")

    monkeypatch.setattr(
        runner,
        "_SOURCES",
        {
            "ok": Source(name="ok", description="", run=ok_run),
            "boom": Source(name="boom", description="", run=boom_run),
        },
    )

    with pytest.raises(RuntimeError, match="boom: no credential"):
        runner.run_all(output_dir=tmp_path, raw_dir=tmp_path)
