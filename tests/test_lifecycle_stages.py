"""Where each sample is in its lifecycle."""

import json
import subprocess

import pytest
from datalad.api import clone

from faire import indexing, planning, rules
from faire.platform.fake import FakePlatform
from indexfix import received, request
from lifefix import GROUP, invoke, merge, runner

pytestmark = pytest.mark.integration

S = {n: f"subject=01,session={n}" for n in ("003", "004", "005")}


@pytest.fixture
def platform(tmp_path):
    return FakePlatform(tmp_path / "hosting")


def index(study, platform, tmp_path, session):
    files = {f"01/{session}/scan.txt": f"scan {session}\n"}
    indexing.index(request(study, platform, received(tmp_path, files, f"in-{session}")))


def propose(study, platform, tmp_path, monkeypatch, session):
    """The derived dataset's pipeline for a sample: its pull request opens."""
    ds = runner(study, platform, tmp_path, "standardized", "dev", name=f"std-{session}")
    due = {
        t.sample["session"]: t
        for t in planning.due_tasks(ds, rules.load(ds.path), default_site="a", update=True)
    }
    out = invoke(
        platform, monkeypatch, "run", "--task", due[session].id, "--dataset", ds.path,
        "--platform-url", "https://x", "--project", f"{GROUP}/standardized",
    )  # fmt: skip
    assert out.exit_code == 0, out.output
    return ds, planning.branch_of(due[session].sample)


def test_the_stage_of_a_sample_is_reported_in_each_stage(study_platform, tmp_path, monkeypatch):
    study, platform = study_platform
    index(study, platform, tmp_path, "003")
    ds, branch = propose(study, platform, tmp_path, monkeypatch, "003")
    pr = platform.pull_requests(platform.get_repository(GROUP, "standardized"))[0]
    merge(ds, branch)  # accepted ...
    platform.merged.add(pr.number)
    ds.repo.call_git(["checkout", "-q", "-B", "main", "origin/main"])
    ds.repo.call_git(["merge", "--no-ff", "-q", "-m", "release", "origin/dev"])
    ds.repo.call_git(["tag", "v1"])  # ... and released
    ds.repo.call_git(["push", "origin", "main", "v1"])

    index(study, platform, tmp_path, "004")
    propose(study, platform, tmp_path, monkeypatch, "004")  # under review
    index(study, platform, tmp_path, "005")  # indexed, nothing run yet

    where = runner(study, platform, tmp_path, "standardized", "dev", name="where")
    out = invoke(
        platform, monkeypatch, "stage", "--dataset", where.path, "--json",
        "--platform-url", "https://x", "--project", f"{GROUP}/standardized",
    )  # fmt: skip
    assert out.exit_code == 0, out.output
    assert json.loads(out.output) == {
        S["003"]: "release",
        S["004"]: "review",
        S["005"]: "collection",
    }

    # naming a sample reports it alone; an unknown one is an error
    one = invoke(platform, monkeypatch, "stage", "--dataset", where.path, S["004"])
    assert one.output.strip() == f"{S['004']}: review"
    assert invoke(platform, monkeypatch, "stage", "--dataset", where.path, "nobody").exit_code == 1


def test_accepted_samples_are_reported_before_the_release(study_platform, tmp_path, monkeypatch):
    study, platform = study_platform
    index(study, platform, tmp_path, "003")
    ds, branch = propose(study, platform, tmp_path, monkeypatch, "003")
    platform.merged.update(
        pr.number for pr in platform.pull_requests(platform.get_repository(GROUP, "standardized"))
    )
    merge(ds, branch)
    out = invoke(platform, monkeypatch, "stage", "--dataset", ds.path, "--json")
    assert json.loads(out.output) == {S["003"]: "accepted"}


def test_an_indexed_sample_of_a_source_dataset_is_at_collection(
    study_platform, tmp_path, monkeypatch
):
    study, platform = study_platform
    index(study, platform, tmp_path, "003")
    url = platform.get_repository(GROUP, "dicoms-a_PrismaFit16001").url
    ds = clone(url, str(tmp_path / "instance"), result_renderer="disabled")
    ds.repo.call_git(["checkout", "-q", "-B", "dev", "origin/dev"])
    out = invoke(platform, monkeypatch, "stage", "--dataset", ds.path, "--json")
    assert json.loads(out.output) == {S["003"]: "collection"}
    assert (
        subprocess.run(["git", "-C", ds.path, "status", "--short"], capture_output=True).stdout
        == b""
    )


@pytest.fixture
def study_platform(project, platform):
    project.init(platform=platform, group=GROUP)
    return project, platform
