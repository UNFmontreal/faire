"""Archival: the study retrievable from the archive alone."""

import shutil
from pathlib import Path

import pytest
from datalad.api import clone

from faire import indexing, remotes
from faire.platform.fake import FakePlatform
from indexfix import git, received, request
from lifefix import GROUP, accept_through_chain, invoke

pytestmark = pytest.mark.integration


@pytest.fixture
def platform(tmp_path):
    return FakePlatform(tmp_path / "hosting")


@pytest.fixture
def released(project, platform, tmp_path, monkeypatch):
    """A study with archival hosts, one sample accepted through the chain, released as v1."""
    root = tmp_path / "archive"
    for dataset in project.doc["dmp"]["dataset"]:
        dataset["distribution"] = [
            d for d in dataset["distribution"] if d["faire"]["stage"] != "archival"
        ]
    for name in ("atlas", "standardized", "analysis"):
        project.add_stage_distribution(name, "archival", "Archive", long_term=True)
        dist = next(
            d
            for ds in project.doc["dmp"]["dataset"]
            if ds["dataset_id"]["identifier"] == name
            for d in ds["distribution"]
            if d["title"] == "Archive"
        )
        dist["host"]["faire"]["parameters"]["directory"] = str(root)
    project.write()
    project.init(platform=platform, group=GROUP)
    indexing.index(request(project, platform, received(tmp_path, {"01/003/scan.txt": "scan\n"})))
    accept_through_chain(project, platform, monkeypatch, tmp_path)
    out = invoke(
        platform, monkeypatch, "release", "v1", "--site", "a",
        "--platform-url", "https://x", "--group", GROUP,
    )  # fmt: skip
    assert out.exit_code == 0, out.output
    return root


def run_archive(project, monkeypatch=None):
    from click.testing import CliRunner

    from faire.cli import main

    args = ["archive", "--root", str(project.ws.root), "--madmp", str(project.madmp)]
    args += ["--site", "a", "--sites-dir", str(project.sites_dir)]
    return CliRunner().invoke(main, args)


def test_the_archive_holds_every_repository_with_relative_references(project, released):
    out = run_archive(project)
    assert out.exit_code == 0, out.output
    names = {p.name for p in released.glob("*.git")}
    assert {"study.git", "standardized.git", "analysis.git", "atlas.git"} <= names
    modules = git(str(released / "study.git"), "show", "v1:.gitmodules")
    assert (
        "../standardized.git" in modules
        and "://" not in modules
        and str(project.tmp) not in modules
    )
    again = run_archive(project)  # nothing changed: the same result
    assert again.exit_code == 0 and git(str(released / "study.git"), "rev-parse", "v1")


def test_the_archived_study_installs_and_serves_every_release_without_the_platform(
    project, platform, released, tmp_path
):
    assert run_archive(project).exit_code == 0
    shutil.move(str(tmp_path / "hosting"), str(tmp_path / "hosting-gone"))  # no platform
    ds = clone(str(released / "study.git"), str(tmp_path / "restored"), result_renderer="disabled")
    # a branch that tracks the archive, set to the release: relative addresses resolve from it
    ds.repo.call_git(["checkout", "-q", "-B", "at-v1", "origin/main"])
    ds.repo.call_git(["reset", "-q", "--hard", "v1"])
    ds.get(".", get_data=False, recursive=True, result_renderer="disabled")
    for path in ("standardized", "analysis", "atlas", "dicoms/a_PrismaFit16001"):
        assert (Path(ds.path) / path / ".git").exists(), path
    std = Path(ds.path) / "standardized"
    from datalad.api import Dataset

    sub = Dataset(std)
    spec = remotes.specs(
        project.dmp.dataset("standardized"), "standardized", project.site, ("archival",)
    )[0]
    remotes.enable(sub, spec)
    processed = std / "01/003/processed.txt"
    sub.get(str(processed), result_renderer="disabled")
    assert processed.read_text()
