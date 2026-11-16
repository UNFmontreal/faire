from click.testing import CliRunner

from faire.cli import main


def test_help_prints_usage():
    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "faire" in result.output


def test_validate_valid_document():
    from pathlib import Path

    path = Path(__file__).parent / "data" / "federated.json"
    result = CliRunner().invoke(main, ["validate", str(path)])
    assert result.exit_code == 0
    assert "valid" in result.output


def test_validate_reports_all_violations_in_one_run(tmp_path):
    import json
    from pathlib import Path

    d = json.loads((Path(__file__).parent / "data" / "federated.json").read_text())
    d["dmp"]["dataset"][3]["faire"]["template"]["version"] = "main"  # unpinned
    d["dmp"]["faire"].pop("coordinator")  # hub without coordinator
    d["dmp"]["dataset"][2]["distribution"][0]["faire"]["filter"] = "foo=bar"  # unparsable
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(d))
    result = CliRunner().invoke(main, ["validate", str(path)])
    assert result.exit_code == 1
    for expected in ("not pinned", "without a coordinator", "cannot be parsed"):
        assert expected in result.output
    assert "3 violation(s)" in result.output
