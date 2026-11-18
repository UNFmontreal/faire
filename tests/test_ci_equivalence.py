"""The single-job fallback and the generated pipeline leave the dataset in the same state.

The generated pipeline is emulated faithfully: for each branch a planning job writes the plan,
`faire ci render` turns it into jobs, and each job's script (the tool invoked with a task or check
identifier) runs in the order the jobs' `needs` give. Pushing a branch starts the pipeline of that
branch, as on a platform. The fallback runs the script of the template's one static job.
"""

import copy
import json
import os
import shlex
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from faire.cli import main
from rulefix import RULES, make_derived, write_source

TEMPLATES = Path(__file__).parent.parent / "templates" / "dataset" / "template"
FALLBACK = TEMPLATES / ".faire" / "ci" / "single-job.gitlab-ci.yml"
ENTRY = TEMPLATES / ".gitlab-ci.yml"

RULESET = copy.deepcopy(RULES)
RULESET["rules"].append(
    {
        "id": "refine",
        "trigger": {"paths": ["{subject}/processed.txt"]},
        "container": "tool",
        "command": "sh -c 'tr a-z A-Z < {inputs} > {outputs}'",
        "inputs": [{"pattern": "{subject}/processed.txt", "required": True}],
        "outputs": ["{subject}/refined.txt"],
    }
)
RULESET["checks"] = [
    {"id": "layout", "command": "test -f .faire/rules.yaml", "blocking": True},
    {"id": "protocol", "command": "false", "blocking": False},  # advisory, and failing
]


@pytest.fixture(autouse=True)
def ci_environment(monkeypatch):
    monkeypatch.setenv("FAIRE_DATASET", "derived")
    monkeypatch.setenv("FAIRE_SITE", "a")
    monkeypatch.setenv("FAIRE_RUNNER_TAGS", json.dumps({"a": ["site-a"]}))


def faire(*words):
    return CliRunner().invoke(main, list(words))


def script_of(line):
    words = shlex.split(line)
    assert words[0] == "faire", line
    return words[1:]


def run_script(lines, allow_failure=False):
    for line in lines:
        out = faire(*script_of(line))
        assert out.exit_code == 0 or allow_failure, f"{line}: {out.output}"


def in_order(jobs):
    """Jobs in an order that respects `needs`."""
    done, pending = [], dict(jobs)
    while pending:
        ready = [n for n, j in pending.items() if all(d in done for d in j.get("needs", []))]
        assert ready, "cyclic needs"
        for name in sorted(ready):
            done.append(name)
            yield name, pending.pop(name)


def pipeline_of(ds, tmp_path):
    """The pipeline of the checked-out branch: plan, render, then every generated job."""
    entry = yaml.safe_load(ENTRY.read_text())
    plan_json, child = tmp_path / "plan.json", tmp_path / "child-pipeline.yml"
    # the planning job's own workspace holds its artifacts, not the dataset's working tree
    os.chdir(tmp_path)
    for line, target in zip(entry["plan"]["script"], (plan_json, child), strict=True):
        command, _, redirect = line.partition(" > ")
        assert redirect == target.name
        args = script_of(command)
        if args[0] == "plan":
            args += ["--dataset", ds.path]
        out = faire(*args)
        assert out.exit_code == 0, f"{line}: {out.output}"
        target.write_text(out.output)
    os.chdir(ds.path)
    jobs = {n: j for n, j in yaml.safe_load(child.read_text()).items() if n != "stages"}
    for _name, job in in_order(jobs):
        run_script(job["script"], allow_failure=job.get("allow_failure", False))
    return jobs


def run_generated(ds, tmp_path):
    seen: dict[str, str] = {}
    for _ in range(10):
        branches = ["dev", *sorted(b for b in ds.repo.get_branches() if b.startswith("feature/"))]
        pending = [b for b in branches if seen.get(b) != ds.repo.get_hexsha(b)]
        if not pending:
            return
        branch = pending[0]
        seen[branch] = ds.repo.get_hexsha(branch)  # the push that starts this pipeline
        ds.repo.call_git(["checkout", branch])
        os.chdir(ds.path)
        pipeline_of(ds, tmp_path)
    raise AssertionError("pipelines keep re-triggering")


def state(ds, branch):
    files = [
        line
        for line in ds.repo.call_git(["ls-tree", "-r", branch]).splitlines()
        # each dataset has its own collection clone, so its pointer differs by construction
        if not line.split("\t")[1].startswith(".") and not line.endswith("code/containers")
    ]
    tasks = [
        line
        for line in ds.repo.call_git(
            ["log", "--reverse", "--format=%B", f"dev..{branch}"]
        ).splitlines()
        if line.startswith("faire-task:")
    ]
    return files, tasks


def test_single_job_fallback_leaves_the_same_state_as_the_generated_pipeline(tmp_path, monkeypatch):
    src = write_source(tmp_path / "src", {"01/a.txt": "one\n", "02/a.txt": "two\n"})
    generated = make_derived(tmp_path / "generated", src, rules=RULESET)
    single = make_derived(tmp_path / "single", src, rules=RULESET)
    monkeypatch.chdir(generated.path)
    run_generated(generated, tmp_path)

    monkeypatch.chdir(single.path)
    single.repo.call_git(["checkout", "dev"])
    fallback = yaml.safe_load(FALLBACK.read_text())["faire"]["script"]
    run_script(fallback)  # `faire run --all`, then `faire test`

    for branch in ("feature/subject-01", "feature/subject-02"):
        files, tasks = state(generated, branch)
        assert state(single, branch) == (files, tasks)
        assert [t.split(": ")[1] for t in tasks] == [
            f"process:subject={branch[-2:]}",
            f"refine:subject={branch[-2:]}",
        ]
        assert any(line.endswith(f"{branch[-2:]}/refined.txt") for line in files)
