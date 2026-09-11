import pytest

from sanctions_lists_etl import available_sources, run_source, runner
from sanctions_lists_etl.base import Source, SourceResult
from sanctions_lists_etl.cli import main


def test_sources_are_registered():
    assert {"ofac", "eu", "un", "uk"} <= set(available_sources())


def test_run_source_end_to_end(sample_xml):
    result = run_source("ofac", xml_path=sample_xml)
    assert result.source == "ofac"
    assert result.record_count == 4


def test_run_eu_source_end_to_end(sample_eu_xml):
    result = run_source("eu", xml_path=sample_eu_xml)
    assert result.source == "eu"
    assert result.record_count == 5


def test_run_un_source_end_to_end(sample_un_xml):
    result = run_source("un", xml_path=sample_un_xml)
    assert result.source == "un"
    assert result.record_count == 7
    assert result.counts_by_type == {"Individual": 4, "Entity": 3}


def test_run_uk_source_end_to_end(sample_uk_xml):
    result = run_source("uk", xml_path=sample_uk_xml)
    assert result.source == "uk"
    assert result.record_count == 5
    assert result.counts_by_type == {"Entity": 2, "Individual": 2, "Vessel": 1}


def test_cli_eu_requires_token_without_xml(capsys, monkeypatch):
    for name in ("EU_FSF_TOKEN", "EU_FSF_TOKEN_FILE", "EU_FSF_URL"):
        monkeypatch.delenv(name, raising=False)
    exit_code = main(["eu"])
    assert exit_code == 1
    assert "EU_FSF_TOKEN" in capsys.readouterr().err


def test_cli_runs_single_source(sample_xml, capsys):
    exit_code = main(["ofac", "--xml", str(sample_xml), "--individuals-entities-only"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "[ofac]" in out
    assert "Vessel" not in out


def test_cli_list(capsys):
    assert main(["--list"]) == 0
    assert "ofac" in capsys.readouterr().out


def test_run_all_exclude_skips_named_sources(monkeypatch):
    ran: list[str] = []

    def make_run(name):
        def _run(**_):
            ran.append(name)
            return SourceResult(source=name, record_count=0)

        return _run

    monkeypatch.setattr(
        runner,
        "_SOURCES",
        {n: Source(name=n, description="", run=make_run(n)) for n in ("a", "b", "c")},
    )

    runner.run_all(exclude=["b"])
    assert ran == ["a", "c"]


def test_run_all_exclude_rejects_unknown_source(monkeypatch):
    monkeypatch.setattr(
        runner, "_SOURCES", {"a": Source(name="a", description="", run=lambda **_: None)}
    )
    with pytest.raises(KeyError, match="nope"):
        runner.run_all(exclude=["nope"])


def test_cli_exclude_only_with_all(sample_xml, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--exclude", "eu", "ofac", "--xml", str(sample_xml)])
    assert exc.value.code == 2
    assert "--exclude only applies" in capsys.readouterr().err


def test_cli_bigquery_requires_project_env(sample_xml, capsys, monkeypatch):
    monkeypatch.delenv("BQ_PROJECT", raising=False)
    exit_code = main(["--bigquery", "ofac", "--xml", str(sample_xml)])
    assert exit_code == 1
    assert "BQ_PROJECT" in capsys.readouterr().err


def test_cli_bigquery_flag_reaches_source_run(monkeypatch):
    monkeypatch.setenv("BQ_PROJECT", "proj")
    monkeypatch.delenv("BQ_DATASET", raising=False)
    seen: dict = {}

    def fake_run(*, bigquery=False, bq_project=None, bq_dataset=None, **_):
        seen.update(bigquery=bigquery, bq_project=bq_project, bq_dataset=bq_dataset)
        return SourceResult(source="ofac", record_count=0)

    monkeypatch.setattr(
        runner,
        "_SOURCES",
        {
            "ofac": Source(
                name="ofac",
                description="",
                run=fake_run,
                configure_parser=lambda p: None,
                options_from_args=lambda a: {},
            )
        },
    )

    exit_code = main(["--bigquery", "ofac"])
    assert exit_code == 0
    assert seen == {"bigquery": True, "bq_project": "proj", "bq_dataset": "sanctions"}


def test_run_all_keeps_going_past_a_failing_source(monkeypatch):
    def ok_run(**_):
        return SourceResult(source="ok", record_count=1)

    def boom_run(**_):
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
        runner.run_all()
