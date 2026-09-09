from openpyxl import load_workbook

from sanctions_lists_etl import available_sources, run_source
from sanctions_lists_etl.cli import main


def test_ofac_is_registered():
    assert "ofac" in available_sources()


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
