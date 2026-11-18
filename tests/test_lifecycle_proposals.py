"""Proposing samples: by hand, and following the `dev` or `pilot` stream of the pipeline."""

import pytest
from datalad.api import clone

from faire import indexing, planning, rules
from faire.platform.fake import FakePlatform
from indexfix import received, request
from lifefix import GROUP, invoke, runner

pytestmark = pytest.mark.integration


@pytest.fixture
def platform(tmp_path):
    return FakePlatform(tmp_path / "hosting")


@pytest.fixture
def study(project, platform):
    project.init(platform=platform, group=GROUP)
    return project


def test_a_manually_pushed_sample_branch_gets_a_pull_request_naming_the_sample(
    study, platform, tmp_path, monkeypatch
):
    atlas = platform.get_repository(GROUP, "atlas")
    ds = clone(atlas.url, str(tmp_path / "atlas"), result_renderer="disabled")
    ds.repo.call_git(["checkout", "-q", "-B", "dev", "origin/dev"])
    ds.repo.call_git(["checkout", "-q", "-b", "feature/subject-01_session-003"])
    (tmp_path / "atlas" / "label.txt").write_text("region\n")
    ds.save(message="a sample by hand", result_renderer="disabled")
    ds.push(to="origin", data="nothing", result_renderer="disabled")
    out = invoke(
        platform, monkeypatch, "propose", "--dataset", ds.path,
        "--platform-url", "https://x", "--project", f"{GROUP}/atlas",
    )  # fmt: skip
    assert out.exit_code == 0, out.output
    [pr] = platform.pull_requests(atlas)
    assert (pr.source, pr.target) == ("feature/subject-01_session-003", "dev")
    assert "subject=01,session=003" in pr.title and "subject=01,session=003" in pr.description
    # proposing again updates it instead of opening another
    invoke(
        platform, monkeypatch, "propose", "--dataset", ds.path,
        "--platform-url", "https://x", "--project", f"{GROUP}/atlas",
    )  # fmt: skip
    assert len(platform.pull_requests(atlas)) == 1


def test_any_other_branch_gets_no_pull_request(study, platform, tmp_path, monkeypatch):
    atlas = platform.get_repository(GROUP, "atlas")
    ds = clone(atlas.url, str(tmp_path / "atlas"), result_renderer="disabled")
    ds.repo.call_git(["checkout", "-q", "-B", "dev", "origin/dev"])
    out = invoke(
        platform, monkeypatch, "propose", "--dataset", ds.path,
        "--platform-url", "https://x", "--project", f"{GROUP}/atlas",
    )  # fmt: skip
    assert out.exit_code == 0 and "not a sample branch" in out.output
    assert not platform.pull_requests(atlas)


def run_pipeline_on(study, platform, tmp_path, monkeypatch, branch):
    """What the derived dataset's pipeline does on `branch` after an indexing trigger."""
    ds = runner(study, platform, tmp_path, "standardized", branch)
    due = planning.due_tasks(ds, rules.load(ds.path), default_site="a", update=True)
    assert len(due) == 1
    out = invoke(
        platform, monkeypatch, "run", "--task", due[0].id, "--dataset", ds.path,
        "--platform-url", "https://x", "--project", f"{GROUP}/standardized",
    )  # fmt: skip
    assert out.exit_code == 0, out.output
    return platform.pull_requests(platform.get_repository(GROUP, "standardized"))


def test_a_production_sample_is_proposed_to_dev_in_the_derived_dataset(
    study, platform, tmp_path, monkeypatch
):
    indexing.index(request(study, platform, received(tmp_path, {"01/003/scan.txt": "scan\n"})))
    [pr] = run_pipeline_on(study, platform, tmp_path, monkeypatch, "dev")
    assert pr.target == "dev" and pr.source.startswith("feature/")


def test_a_pilot_sample_is_proposed_to_pilot_in_the_derived_dataset(
    study, platform, tmp_path, monkeypatch
):
    pilot = {"01/003/scan.txt": "scan\n", "01/003/PILOT": ""}
    indexing.index(request(study, platform, received(tmp_path, pilot)))
    [pr] = run_pipeline_on(study, platform, tmp_path, monkeypatch, "pilot")
    assert pr.target == "pilot" and pr.source.startswith("feature/")
