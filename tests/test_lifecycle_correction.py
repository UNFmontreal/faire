"""Corrections to accepted samples, and reprocessing on request."""

import json
from pathlib import Path

import pytest

from faire import execute, indexing, planning, rules
from faire.ciplan import CiPlan
from faire.platform.fake import FakePlatform
from indexfix import received, request
from lifefix import GROUP, fire_downstream, invoke, merge, runner
from rulefix import make_derived, write_source

pytestmark = pytest.mark.integration


@pytest.fixture
def platform(tmp_path):
    return FakePlatform(tmp_path / "hosting")


def test_a_corrected_sample_gets_a_new_pull_request_replacing_its_results(
    project, platform, tmp_path, monkeypatch
):
    project.init(platform=platform, group=GROUP)
    indexing.index(request(project, platform, received(tmp_path, {"01/003/scan.txt": "v1\n"})))
    ds = runner(project, platform, tmp_path, "standardized", "dev")
    [task] = planning.due_tasks(ds, rules.load(ds.path), default_site="a", update=True)
    args = [
        "--dataset",
        ds.path,
        "--platform-url",
        "https://x",
        "--project",
        f"{GROUP}/standardized",
    ]
    assert invoke(platform, monkeypatch, "run", "--task", task.id, *args).exit_code == 0
    branch = planning.branch_of(task.sample)
    before = merge(ds, branch)
    assert (Path(ds.path) / "01/003/processed.txt").read_text() == "v1\n"
    started = fire_downstream(platform, monkeypatch, "standardized", ds, before, tmp_path)
    assert [p for p, _, _ in started] == [f"{GROUP}/analysis"]
    assert planning.due_tasks(ds, rules.load(ds.path), default_site="a", update=True) == []

    # a fix to the accepted sample is merged upstream: the derived dataset is triggered again
    platform.pipelines.clear()
    fix = indexing.index(
        request(project, platform, received(tmp_path, {"01/003/scan.txt": "v2\n"}, "fix"))
    )
    assert fix.commit and fix.triggered == [f"{GROUP}/standardized"]
    [again] = planning.due_tasks(ds, rules.load(ds.path), default_site="a", update=True)
    assert again.id == task.id  # the same sample, from the corrected state
    assert invoke(platform, monkeypatch, "run", "--task", again.id, *args).exit_code == 0
    assert ds.repo.get_active_branch() == branch  # a new branch, started from `dev` again
    assert (Path(ds.path) / "01/003/processed.txt").read_text() == "v2\n"
    ds.repo.call_git(["checkout", "-q", "dev"])  # while `dev` still holds the accepted results
    assert (Path(ds.path) / "01/003/processed.txt").read_text() == "v1\n"
    ds.repo.call_git(["checkout", "-q", branch])

    # merged in turn, the correction starts the next level again
    platform.pipelines.clear()
    before = merge(ds, branch)
    again_down = fire_downstream(platform, monkeypatch, "standardized", ds, before, tmp_path)
    assert [(p, b) for p, b, _ in again_down] == [(f"{GROUP}/analysis", "dev")]


def test_reprocessing_named_samples_opens_one_pull_request_for_each(tmp_path, monkeypatch):
    src = write_source(
        tmp_path / "src", {"01/a.txt": "one\n", "02/a.txt": "two\n", "03/a.txt": "3\n"}
    )
    ds = make_derived(tmp_path, src)
    ruleset = rules.load(ds.path)
    for task in ("process:subject=01", "process:subject=02", "process:subject=03"):  # accepted
        out = execute.run_task(ds, ruleset, task, env={})
        ds.repo.call_git(["checkout", "dev"])
        ds.repo.call_git(["merge", "--no-ff", "-q", "-m", "merge", out.branch])
    assert planning.due_tasks(ds, ruleset, default_site="a") == []

    platform = FakePlatform(tmp_path / "hosting")
    repo = platform.ensure_repository(platform.ensure_group("g").path, "derived")
    out = invoke(
        platform, monkeypatch, "reprocess", "subject=01", "subject=02",
        "--dataset-id", "derived", "--platform-url", "https://x", "--project", "g/derived",
    )  # fmt: skip
    assert out.exit_code == 0, out.output
    [(project, ref, variables)] = platform.pipelines
    assert (project, ref) == ("g/derived", "dev")
    assert variables["FAIRE_REPROCESS"] == "subject=01;subject=02"

    named = variables["FAIRE_REPROCESS"]
    # the pipeline that starts: the plan names the two samples, not the third
    out = invoke(
        platform, monkeypatch, "plan", "--dataset", ds.path, "--no-update",
        env={"FAIRE_DATASET": "derived", "FAIRE_SITE": "a", "FAIRE_REPROCESS": named},
    )  # fmt: skip
    plan = CiPlan.from_json(out.output)
    assert [t.id for t in plan.tasks] == ["process:subject=01", "process:subject=02"]
    for task in plan.tasks:
        ds.repo.call_git(["checkout", "dev"])
        done = invoke(
            platform, monkeypatch, "run", "--task", task.id, "--dataset", ds.path,
            "--platform-url", "https://x", "--project", "g/derived",
        )  # fmt: skip
        assert done.exit_code == 0, done.output
    assert sorted(pr.source for pr in platform.pull_requests(repo)) == [
        "feature/subject-01",
        "feature/subject-02",
    ]
    assert json.loads(out.output)["samples"] == []
