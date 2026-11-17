import copy
import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from datalad.api import clone

from faire import ciplan, planning, rules
from faire.cli import main
from faire.render import gitlab as gitlab_renderer
from rulefix import RULES, make_derived, write_source


def invoke(*args, env=None):
    return CliRunner().invoke(main, [str(a) for a in args], env=env or {}, catch_exceptions=False)


@pytest.fixture
def world(tmp_path):
    src = write_source(tmp_path / "src", {"01/a.txt": "one\n", "02/a.txt": "two\n"})
    return src, make_derived(tmp_path, src)


def test_plan_command_prints_the_task_list(world):
    _src, ds = world
    out = invoke("plan", "--dataset", ds.path, "--dataset-id", "derived", "--site", "a")
    assert out.exit_code == 0
    parsed = ciplan.CiPlan.from_json(out.output)
    assert [t.id for t in parsed.tasks] == ["process:subject=01", "process:subject=02"]


def test_plan_by_hand_equals_plan_in_ci(world):
    _src, ds = world
    args = ["plan", "--dataset", ds.path, "--dataset-id", "derived", "--site", "a"]
    hand = invoke(*args).output
    ci = invoke(*args, env={"CI": "true", "CI_COMMIT_SHA": "1" * 40, "GITLAB_CI": "true"}).output
    assert hand == ci


def test_run_task_locally_without_pull_request(world):
    _src, ds = world
    out = invoke("run", "--dataset", ds.path, "--task", "process:subject=01", "--no-push")
    assert out.exit_code == 0 and "done" in out.output
    assert ds.repo.get_active_branch() == "feature/subject-01"
    assert (Path(ds.path) / "01/processed.txt").read_text() == "one\n"


def test_local_and_ci_runs_give_the_same_tree(tmp_path):
    src = write_source(tmp_path / "src", {"01/a.txt": "one\n"})
    local = make_derived(tmp_path / "l", src) if (tmp_path / "l").mkdir() is None else None
    ci = make_derived(tmp_path / "c", src) if (tmp_path / "c").mkdir() is None else None
    invoke("run", "--dataset", local.path, "--task", "process:subject=01", "--no-push")
    invoke(
        "run",
        "--dataset",
        ci.path,
        "--task",
        "process:subject=01",
        "--no-push",
        env={"CI": "true", "FAIRE_AUTOMATION_NAME": "bot", "FAIRE_AUTOMATION_EMAIL": "bot@x"},
    )
    tree = lambda ds: ds.repo.call_git(["rev-parse", "feature/subject-01:01"])  # noqa: E731
    assert tree(local) == tree(ci)
    assert ci.repo.call_git(["log", "-1", "--format=%an"]).strip() == "bot"


def test_failed_task_keeps_its_log_in_the_artifact_directory(tmp_path):
    src = write_source(tmp_path / "src", {"01/a.txt": "one\n"})
    bad = copy.deepcopy(RULES)
    bad["rules"][0]["command"] = "sh -c 'echo boom >&2; exit 3'"
    ds = make_derived(tmp_path, src, rules=bad)
    out = CliRunner().invoke(
        main, ["run", "--dataset", ds.path, "--task", "process:subject=01", "--no-push"]
    )
    assert out.exit_code == 1 and "execution failed" in out.output
    logs = list((Path(ds.path) / ".faire/logs").glob("*.failed.log"))
    assert len(logs) == 1 and "exit" in logs[0].read_text().lower() or logs[0].read_text()


def test_missing_secret_fails_before_anything_with_exit_one(world):
    _src, ds = world
    out = CliRunner().invoke(
        main,
        ["run", "--dataset", ds.path, "--task", "process:subject=01"],
        env={"FAIRE_SECRETS": "S3_KEY"},
    )
    assert out.exit_code == 1 and "S3_KEY" in out.output


def test_unmet_required_input_exits_zero_and_says_so(tmp_path):
    src = write_source(tmp_path / "src", {"01/a.txt": "one\n", "02/b.nii": "x\n"})
    ds = make_derived(tmp_path, src)
    out = invoke("run", "--dataset", ds.path, "--task", "process:subject=02", "--no-push")
    assert out.exit_code == 0 and "unmet required input" in out.output
    assert ds.repo.get_active_branch() == "dev"


def test_test_command_lists_and_runs_checks_on_the_branch_state(world):
    _src, ds = world
    invoke("run", "--dataset", ds.path, "--task", "process:subject=01", "--no-push")
    listed = json.loads(invoke("test", "--dataset", ds.path, "--list").output)
    assert listed == [{"id": "layout", "blocking": True}, {"id": "extra", "blocking": False}]
    ok = invoke("test", "--dataset", ds.path, "--check", "layout")
    assert ok.exit_code == 0 and "layout: passed" in ok.output
    ds.repo.call_git(["checkout", "dev"])
    assert invoke("test", "--dataset", ds.path, "--list").output.strip() == "[]"


def test_a_failing_check_reflects_in_the_exit_status(tmp_path):
    src = write_source(tmp_path / "src", {"01/a.txt": "one\n"})
    doc = copy.deepcopy(RULES)
    doc["checks"] = [{"id": "never", "command": "exit 4", "blocking": True}]
    ds = make_derived(tmp_path, src, rules=doc)
    out = CliRunner().invoke(main, ["test", "--dataset", ds.path, "--check", "never"])
    assert out.exit_code == 1 and "never: failed" in out.output


def test_tasks_are_placed_on_the_site_of_the_samples_instrument(tmp_path):
    a = write_source(tmp_path / "a", {"01/a.txt": "one\n"})
    b = write_source(tmp_path / "b", {"02/a.txt": "two\n"})
    doc = copy.deepcopy(RULES)
    doc["rules"][0]["inputs"][0]["pattern"] = "sourcedata/src/*/{subject}/*.txt"
    ds = make_derived(tmp_path, {"a_mri": a, "b_mri": b}, rules=doc)
    result = planning.make_plan(
        ds,
        rules.load(ds.path),
        dataset_id="d",
        branch="dev",
        default_site="a",
        instances={"src": {"a_mri": "a", "b_mri": "b"}},
    )
    assert {t.id: t.site for t in result.tasks} == {
        "process:subject=01": "a",
        "process:subject=02": "b",
    }
    rendered = gitlab_renderer.render(result, {"a": ["site-a"], "b": ["site-b"]})
    tags = {name: job.get("tags") for name, job in rendered.items() if isinstance(job, dict)}
    by_task = {n: t for n, t in tags.items() if t}
    assert sorted(map(tuple, by_task.values())) == [("site-a",), ("site-b",)]


def test_accepted_result_is_reexecutable_in_a_fresh_clone(world, tmp_path):
    _src, ds = world
    invoke("run", "--dataset", ds.path, "--task", "process:subject=01", "--no-push")
    ds.repo.call_git(["checkout", "dev"])
    ds.repo.call_git(["merge", "--no-ff", "-m", "accept", "feature/subject-01"])
    sha = ds.repo.call_git(["log", "--grep=faire-task", "-1", "--format=%H"]).strip()
    message = ds.repo.call_git(["log", "-1", "--format=%B", sha])
    for trailer in (
        "faire-rule-version: ",
        "faire-container: tool test-1",
        "faire-source: sourcedata/src=",
    ):
        assert trailer in message
    fresh = clone(ds.path, tmp_path / "fresh", result_renderer="disabled")
    fresh.get("sourcedata/src", get_data=False, result_renderer="disabled")
    fresh.repo.call_git(["checkout", f"{sha}^"])  # the state just before the result existed
    assert not (Path(fresh.path) / "01/processed.txt").exists()
    fresh.rerun(revision=sha, since="", result_renderer="disabled")
    assert (Path(fresh.path) / "01/processed.txt").read_text() == "one\n"


def test_run_pushes_and_opens_a_pull_request_with_report_links(tmp_path, monkeypatch):
    from faire.platform.fake import FakePlatform

    src = write_source(tmp_path / "src", {"01/a.txt": "one\n"})
    ds = make_derived(tmp_path, src)
    platform = FakePlatform(tmp_path / "platform")
    repo = platform.ensure_repository(platform.ensure_group("study").path, "derived")
    ds.siblings("add", name="origin", url=repo.url, result_renderer="disabled")
    ds.push(to="origin", result_renderer="disabled")
    monkeypatch.setattr("faire.cli.factory.connect", lambda *a, **k: platform)
    args = ["run", "--dataset", ds.path, "--task", "process:subject=01"]
    out = invoke(*args, "--platform-url", "http://x", "--project", "study/derived")
    assert out.exit_code == 0, out.output
    [pr] = platform.list_pull_requests(repo)
    assert (pr.source, pr.target) == ("feature/subject-01", "dev")
    assert "01/processed.txt" in pr.description
    # run again (a rerun): same pull request, updated; no new one
    invoke(*args, "--platform-url", "http://x", "--project", "study/derived")
    assert len(platform.list_pull_requests(repo)) == 1
    # local use: no pull request
    monkeypatch.setattr("faire.cli.factory.connect", lambda *a, **k: pytest.fail("no platform"))
    out = invoke(*args, "--no-pull-request", "--platform-url", "http://x", "--project", "s/d")
    assert out.exit_code == 0
