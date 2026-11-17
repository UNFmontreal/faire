from pathlib import Path

import pytest
from datalad.api import clone

from faire import execute, publish, rules
from faire.platform.fake import FakePlatform
from rulefix import enable_directory_remote, make_derived, write_source


@pytest.fixture
def setup(tmp_path):
    src = write_source(tmp_path / "src", {"01/a.txt": "one\n"})
    ds = make_derived(tmp_path, src, annex=True)
    platform = FakePlatform(tmp_path / "platform")
    repo = platform.ensure_repository(platform.ensure_group("study").path, "derived")
    ds.siblings("add", name="origin", url=repo.url, result_renderer="disabled")
    storage = tmp_path / "review-storage"
    storage.mkdir()
    ds.repo.init_remote(
        "review-store", ["type=directory", f"directory={storage}", "encryption=none"]
    )
    ds.repo.set_preferred_content("wanted", "anything", remote="review-store")
    ds.push(to="origin", result_renderer="disabled")
    return ds, platform, repo


def test_fresh_clone_of_the_branch_retrieves_every_output(setup, tmp_path):
    ds, platform, repo = setup
    out = execute.run_task(ds, rules.load(ds.path), "process:subject=01", env={})
    result = publish.push_results(ds, out.branch)
    assert "review-store" in result.pushed_to and "origin" in result.pushed_to
    fresh = clone(repo.url, tmp_path / "fresh", result_renderer="disabled")
    fresh.repo.call_git(["checkout", out.branch])
    enable_directory_remote(fresh, "review-store", tmp_path / "review-storage")
    fresh.get("01/processed.txt", result_renderer="disabled")
    assert (Path(fresh.path) / "01/processed.txt").read_text() == "one\n"


def test_pull_request_is_created_then_updated_with_report_links(setup):
    ds, platform, repo = setup
    kw = dict(target="dev", title="process subject 01", task_ids=["process:subject=01"])
    first = publish.open_pull_request(platform, repo, "feature/subject-01", listing=[], **kw)
    second = publish.open_pull_request(
        platform, repo, "feature/subject-01", listing=["01/report.html"], **kw
    )
    assert first.number == second.number
    assert "01/report.html" in second.description
    assert platform.file_url(repo, "feature/subject-01", "01/report.html") in second.description
    again = publish.open_pull_request(
        platform, repo, "feature/subject-01", listing=["01/report.html", "01/other.html"], **kw
    )
    assert again.number == first.number and "01/other.html" in again.description
