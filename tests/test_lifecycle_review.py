"""Review: a second source updating an open pull request, advisory checks, pilot streams."""

from pathlib import Path

import pytest

from faire import indexing, planning, rules
from faire.platform.fake import FakePlatform
from indexfix import received, request
from lifefix import GROUP, fire_downstream, invoke, merge, runner
from rulefix import add_samples, make_derived, write_source

pytestmark = pytest.mark.integration


@pytest.fixture
def platform(tmp_path):
    return FakePlatform(tmp_path / "hosting")


@pytest.fixture
def study(project, platform):
    project.init(platform=platform, group=GROUP)
    return project


# -- 8.3 a second trigger updates the open pull request ----------------------------------------

JOIN = {
    "rules": [
        {
            "id": "join",
            "trigger": {"source": "src"},
            "container": "tool",
            "command": "sh -c 'mkdir -p {subject} && cat {inputs} > {outputs}'",
            "inputs": [
                {"pattern": "sourcedata/src/{subject}/*.txt", "required": True},
                {"pattern": "sourcedata/other/{subject}/*.txt"},
            ],
            "outputs": ["{subject}/joined.txt"],
        }
    ]
}


def test_a_second_source_updates_the_open_pull_request(tmp_path, monkeypatch):
    first = write_source(tmp_path / "first", {"01/a.txt": "from the first\n"})
    second = write_source(tmp_path / "second", {"README": "nothing yet\n"})
    ds = make_derived(tmp_path, first, rules=JOIN)
    ds.clone(source=second.path, path="sourcedata/other", result_renderer="disabled")
    ds.save(message="a second source", result_renderer="disabled")
    platform = FakePlatform(tmp_path / "hosting")
    repo = platform.ensure_repository(platform.ensure_group("g").path, "derived")
    args = ["run", "--task", "join:subject=01", "--dataset", ds.path]
    args += ["--platform-url", "https://x", "--project", "g/derived"]

    assert invoke(platform, monkeypatch, *args).exit_code == 0
    branch = ds.repo.get_active_branch()
    assert (Path(ds.path) / "01/joined.txt").read_text() == "from the first\n"
    assert len(platform.pull_requests(repo)) == 1

    # the second source delivers the same sample while the pull request is still open
    add_samples(second, {"01/b.txt": "from the second\n"})
    ds.repo.call_git(["checkout", "dev"])  # the pipeline that the second source's merge starts
    out = invoke(platform, monkeypatch, *args)
    assert out.exit_code == 0, out.output
    assert ds.repo.get_active_branch() == branch  # the same branch: no second pull request
    assert len(platform.pull_requests(repo)) == 1
    assert (Path(ds.path) / "01/joined.txt").read_text() == "from the first\nfrom the second\n"
    pointer = ds.repo.call_git(["ls-tree", branch, "sourcedata/other"]).split()[2]
    assert pointer == second.repo.get_hexsha()  # it shows the second source's merged state
    runs = ds.repo.call_git(["log", "dev.." + branch, "--format=%B"])
    assert runs.count("faire-task: join:subject=01") == 2  # the rule ran again on it


# -- 8.4 advisory checks and deviating samples -------------------------------------------------

ADVISORY = {
    "rules": [JOIN["rules"][0]],
    "checks": [
        {"id": "protocol", "command": "echo 'missing 01/anat.nii' >&2; exit 1", "blocking": False},
        {"id": "layout", "command": "true", "blocking": True},
    ],
}


def test_an_advisory_check_warns_without_failing_the_job(tmp_path, monkeypatch):
    src = write_source(tmp_path / "src", {"01/a.txt": "x\n"})
    ds = make_derived(tmp_path, src, rules=ADVISORY)
    ds.repo.call_git(["checkout", "-q", "-b", "feature/subject-01"])
    out = invoke(FakePlatform(tmp_path / "h"), monkeypatch, "test", "--dataset", ds.path)
    assert out.exit_code == 0
    assert "missing 01/anat.nii" in out.output and "protocol: failed (advisory)" in out.output
    assert "layout: passed" in out.output


def test_a_failing_blocking_check_fails(tmp_path, monkeypatch):
    broken = {**ADVISORY, "checks": [{"id": "layout", "command": "false", "blocking": True}]}
    src = write_source(tmp_path / "src", {"01/a.txt": "x\n"})
    ds = make_derived(tmp_path, src, rules=broken)
    ds.repo.call_git(["checkout", "-q", "-b", "feature/subject-01"])
    out = invoke(FakePlatform(tmp_path / "h"), monkeypatch, "test", "--dataset", ds.path)
    assert out.exit_code == 1 and "layout: failed" in out.output


def test_a_deviating_sample_opens_no_downstream_pull_request_and_no_failure(tmp_path, monkeypatch):
    # the downstream dataset requires `b.txt`, which the accepted sample does not have
    needs_b = {
        "rules": [
            {
                "id": "join",
                "trigger": {"source": "src"},
                "container": "tool",
                "command": "sh -c 'mkdir -p {subject} && cat {inputs} > {outputs}'",
                "inputs": [{"pattern": "sourcedata/src/{subject}/b.txt", "required": True}],
                "outputs": ["{subject}/joined.txt"],
            }
        ]
    }
    src = write_source(tmp_path / "src", {"01/a.txt": "only a\n"})
    ds = make_derived(tmp_path, src, rules=needs_b)
    platform = FakePlatform(tmp_path / "hosting")
    repo = platform.ensure_repository(platform.ensure_group("g").path, "derived")
    head = ds.repo.get_hexsha()
    assert planning.due_tasks(ds, rules.load(ds.path), default_site="a", update=True) == []
    out = invoke(
        platform, monkeypatch, "run", "--task", "join:subject=01", "--dataset", ds.path,
        "--platform-url", "https://x", "--project", "g/derived",
    )  # fmt: skip
    assert out.exit_code == 0 and "skipped" in out.output  # silently: nothing to report as failed
    assert not platform.pull_requests(repo) and ds.repo.get_hexsha() == head


# -- 8.5 the pilot stream ----------------------------------------------------------------------


def run_task_on(study, platform, tmp_path, monkeypatch, repo_name, branch):
    ds = runner(study, platform, tmp_path, repo_name, branch)
    [task] = planning.due_tasks(ds, rules.load(ds.path), default_site="a", update=True)
    out = invoke(
        platform, monkeypatch, "run", "--task", task.id, "--dataset", ds.path,
        "--platform-url", "https://x", "--project", f"{GROUP}/{repo_name}",
    )  # fmt: skip
    assert out.exit_code == 0, out.output
    return ds, task


def test_a_pilot_sample_cascades_to_the_pilot_branches_downstream(
    study, platform, tmp_path, monkeypatch
):
    pilot = {"01/003/scan.txt": "scan\n", "01/003/PILOT": ""}
    indexing.index(request(study, platform, received(tmp_path, pilot)))
    ds, task = run_task_on(study, platform, tmp_path, monkeypatch, "standardized", "pilot")
    [pr] = platform.pull_requests(platform.get_repository(GROUP, "standardized"))
    assert pr.target == "pilot"

    before = merge(ds, planning.branch_of(task.sample), into="pilot")
    started = fire_downstream(platform, monkeypatch, "standardized", ds, before, tmp_path)
    assert [(p, b) for p, b, _ in started] == [(f"{GROUP}/analysis", "pilot")]

    run_task_on(study, platform, tmp_path, monkeypatch, "analysis", "pilot")
    [pr] = platform.pull_requests(platform.get_repository(GROUP, "analysis"))
    assert pr.target == "pilot"  # and the next level follows the same stream
    assert not platform.pull_requests(platform.get_repository(GROUP, "atlas"))


def test_protocol_expectations_from_pilots_are_used_on_the_next_production_sample(
    study, platform, tmp_path, monkeypatch
):
    pilot = {"01/003/scan.txt": "scan\n", "01/003/PILOT": ""}
    indexing.index(request(study, platform, received(tmp_path, pilot)))
    ds, task = run_task_on(study, platform, tmp_path, monkeypatch, "standardized", "pilot")
    merge(ds, planning.branch_of(task.sample), into="pilot")
    # the curator adds a report to the accepted pilot sample, then derives the expectations
    report = Path(ds.path) / "01/003/report.html"
    report.write_text("<html></html>\n")
    ds.save(message="report of the pilot", result_renderer="disabled")
    ds.repo.call_git(["push", "origin", "pilot"])
    import subprocess

    done = subprocess.run(
        ["python3", ".faire/protocol.py", "learn"], cwd=ds.path, capture_output=True, text=True
    )
    assert done.returncode == 0, done.stderr
    expected = (Path(ds.path) / ".faire/protocol.yaml").read_text()
    assert "{subject}/{session}/processed.txt" in expected
    assert "{subject}/{session}/report.html" in expected
    # accepted into `dev`, the expectations apply to what follows
    ds.repo.call_git(["checkout", "-q", "-B", "dev", "origin/dev"])
    (Path(ds.path) / ".faire/protocol.yaml").write_text(expected)
    ds.save(message="protocol from the pilot", result_renderer="disabled")
    ds.repo.call_git(["push", "origin", "dev"])

    indexing.index(request(study, platform, received(tmp_path, {"01/004/scan.txt": "scan\n"}, "p")))
    prod, _ = run_task_on(study, platform, tmp_path, monkeypatch, "standardized", "dev")
    out = invoke(platform, monkeypatch, "test", "--dataset", prod.path)
    assert out.exit_code == 0  # advisory: the sample can still be merged
    assert "warning: the protocol expects 01/004/report.html" in out.output
    assert "protocol: failed (advisory)" in out.output
    # while the pilot sample's own check passed against the expectations it taught
    assert "01/004/processed.txt" not in out.output
