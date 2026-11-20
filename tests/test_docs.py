"""The documentation's commands exist, the quick-start runs, the examples are the tested ones."""

import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from faire.cli import main

ROOT = Path(__file__).parent.parent
GUIDE = (ROOT / "docs" / "guide.md").read_text()
BLOCK = re.compile(r"```sh( quickstart)?\n(.*?)```", re.S)


def documented():
    for match in BLOCK.finditer(GUIDE):
        for line in match.group(2).splitlines():
            if line.startswith("faire "):
                yield bool(match.group(1)), line


def command_of(tokens):
    command = main
    used = 0
    for token in tokens:
        if isinstance(command, click.Group) and token in command.commands:
            command = command.commands[token]
            used += 1
        else:
            break
    return command, used


@pytest.mark.parametrize("line", sorted({line for _q, line in documented()}))
def test_every_documented_command_and_option_exists(line):
    tokens = shlex.split(line)[1:]
    command, used = command_of(tokens)
    assert not isinstance(command, click.Group), line
    known = {opt for p in command.params for opt in (*p.opts, *p.secondary_opts)}
    for token in tokens[used:]:
        if token.startswith("--"):
            assert token in known, f"{line}: {token}"


@pytest.mark.integration
def test_the_quick_start_runs_from_a_clean_checkout_in_local_only_mode(tmp_path):
    out = tmp_path / "out"
    subprocess.run(
        [sys.executable, str(ROOT / "examples/gitlab-demo/build.py"), str(out)], check=True
    )
    steps = [line for quick, line in documented() if quick]
    assert len(steps) >= 3
    for line in steps:
        tokens = [t.replace("$OUT", str(out)) for t in shlex.split(line)[1:]]
        tokens = [str(ROOT / t) if t == "templates/study" else t for t in tokens]
        result = CliRunner().invoke(main, tokens)
        assert result.exit_code == 0, f"{line}\n{result.output}"
    assert (out / "ws" / "study" / "madmp.json").exists()


def test_the_published_examples_are_the_tested_ones_and_valid():
    for name in ("single_site.json", "federated.json"):
        published = ROOT / "examples" / "madmp" / name
        assert published.read_text() == (ROOT / "tests" / "data" / name).read_text()
        assert CliRunner().invoke(main, ["validate", str(published)]).exit_code == 0


@pytest.mark.integration
def test_the_stamped_answers_marked_checked_hold_for_the_example(project, tmp_path):
    project.init()
    ws = project.ws
    study = ws.study
    modules = (study / ".gitmodules").read_text()
    for name in ("standardized", "analysis", "atlas"):  # must/001, must/002
        assert f"path = {name}" in modules
    derived = ws.repos / "standardized"
    assert "sourcedata/dicoms" in (derived / ".gitmodules").read_text()
    for repo in (study, derived):  # must/007
        assert (repo / "README.md").exists()
    licence = (derived / "LICENSE").read_text()  # must/018, should/011
    assert licence.strip()
    assert shutil.which("git")
