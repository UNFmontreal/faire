"""The study release: consistent, tagged everywhere, repeatable."""

from pathlib import Path

import pytest

from faire import indexing, planning, release, rules
from faire.platform.fake import FakePlatform
from indexfix import git, received, request
from lifefix import GROUP, fire_downstream, invoke, merge, runner

pytestmark = pytest.mark.integration

REPOS = {
    "dicoms-a_PrismaFit16001": "dicoms/a_PrismaFit16001",
    "atlas": "atlas",
    "standardized": "standardized",
    "analysis": "analysis",
}


@pytest.fixture
def platform(tmp_path):
    return FakePlatform(tmp_path / "hosting")


@pytest.fixture
def study(project, platform):
    project.init(platform=platform, group=GROUP)
    return project


def do_release(platform, monkeypatch, tag):
    return invoke(
        platform, monkeypatch, "release", tag, "--site", "a",
        "--platform-url", "https://x", "--group", GROUP,
    )  # fmt: skip


def url(platform, name):
    return platform.get_repository(GROUP, name).url


def tags(platform, name):
    return git(url(platform, name), "tag", "--list")


def test_a_consistent_project_is_tagged_everywhere_and_the_study_records_it(
    study, platform, monkeypatch
):
    heads = {name: git(url(platform, name), "rev-parse", "dev") for name in REPOS}
    out = do_release(platform, monkeypatch, "v1")
    assert out.exit_code == 0, out.output
    for name in REPOS:
        assert tags(platform, name) == "v1"
        assert git(url(platform, name), "rev-parse", "v1") == heads[name]
        assert git(url(platform, name), "rev-parse", "main") == heads[name]  # `dev` is in `main`
    # the study at v1 references exactly the tagged revisions
    assert tags(platform, "study") == "v1"
    for name, where in REPOS.items():
        entry = git(url(platform, "study"), "ls-tree", "v1", where).split()
        assert entry[1] == "commit" and entry[2] == heads[name]


def test_a_derived_dataset_behind_its_source_stops_the_release(
    study, platform, tmp_path, monkeypatch
):
    study_before = git(url(platform, "study"), "rev-parse", "main")
    files = {"01/003/scan.txt": "scan\n"}
    indexing.index(request(study, platform, received(tmp_path, files)))  # the source moves on
    out = do_release(platform, monkeypatch, "v1")
    assert out.exit_code == 1
    assert "behind: standardized references an older state of dicoms-a_PrismaFit16001" in out.output
    assert "refused: nothing was tagged" in out.output
    for name in [*REPOS, "study"]:
        assert tags(platform, name) == ""  # no dataset tagged
    assert git(url(platform, "study"), "rev-parse", "main") == study_before


def test_pilot_samples_are_not_part_of_a_release(study, platform, tmp_path, monkeypatch):
    pilot = {"01/003/scan.txt": "scan\n", "01/003/PILOT": ""}
    out = indexing.index(request(study, platform, received(tmp_path, pilot)))
    assert out.pilot
    assert do_release(platform, monkeypatch, "v1").exit_code == 0
    instance = url(platform, "dicoms-a_PrismaFit16001")
    assert git(instance, "rev-parse", "pilot") != git(instance, "rev-parse", "v1")
    inside = git(instance, "branch", "--contains", out.commit, "--list", "main")
    assert inside == ""  # the pilot sample's commit is not in `main`, nor in the tag
    assert git(instance, "tag", "--contains", out.commit) == ""


def test_a_tag_that_exists_elsewhere_stops_the_release(study, platform, monkeypatch, tmp_path):
    work = Path(tmp_path / "w")
    import subprocess

    subprocess.run(["git", "clone", "-q", url(platform, "atlas"), str(work)], check=True)
    subprocess.run(["git", "-C", str(work), "commit", "-q", "--allow-empty", "-m", "x"], check=True)
    subprocess.run(["git", "-C", str(work), "tag", "v1"], check=True)
    subprocess.run(["git", "-C", str(work), "push", "-q", "origin", "v1"], check=True)
    out = do_release(platform, monkeypatch, "v1")
    assert out.exit_code == 1 and "atlas already has a tag v1" in out.output
    assert tags(platform, "analysis") == ""


def test_two_successive_releases_stay_retrievable_by_tag(study, platform, tmp_path, monkeypatch):
    assert do_release(platform, monkeypatch, "v1").exit_code == 0

    # a sample goes through the whole chain and is accepted at each level
    indexing.index(request(study, platform, received(tmp_path, {"01/003/scan.txt": "scan\n"})))
    std = runner(study, platform, tmp_path, "standardized", "dev")
    [task] = planning.due_tasks(std, rules.load(std.path), default_site="a", update=True)
    args = ["--platform-url", "https://x"]
    invoke(
        platform, monkeypatch, "run", "--task", task.id, "--dataset", std.path, *args,
        "--project", f"{GROUP}/standardized",
    )  # fmt: skip
    before = merge(std, planning.branch_of(task.sample))
    fire_downstream(platform, monkeypatch, "standardized", std, before, tmp_path)
    ana = runner(study, platform, tmp_path, "analysis", "dev")
    [task] = planning.due_tasks(ana, rules.load(ana.path), default_site="a", update=True)
    invoke(
        platform, monkeypatch, "run", "--task", task.id, "--dataset", ana.path, *args,
        "--project", f"{GROUP}/analysis",
    )  # fmt: skip
    merge(ana, planning.branch_of(task.sample))

    second = do_release(platform, monkeypatch, "v2")
    assert second.exit_code == 0, second.output
    for name in [*REPOS, "study"]:
        assert tags(platform, name).split() == ["v1", "v2"]

    # both can be checked out: the first without the sample, the second with it
    for tag, expected in (("v1", False), ("v2", True)):
        ds = release.checkout_release(platform, GROUP, tag, tmp_path / f"at-{tag}")
        instance = Path(ds.path) / "dicoms/a_PrismaFit16001/01/003/scan.txt"
        assert (instance.exists() or instance.is_symlink()) is expected, tag
        assert (Path(ds.path) / "standardized/01/003/processed.txt").is_symlink() is expected


# -- 8.11 what a release references, 8.12 licenses -------------------------------------------------


def test_the_report_lists_external_collections_and_restricted_sources(study, platform, monkeypatch):
    out = do_release(platform, monkeypatch, "v1")
    assert out.exit_code == 0, out.output
    lines = out.output.splitlines()
    external = [x for x in lines if x.startswith("externally managed: containers of")]
    assert len(external) == 3  # `atlas`, `standardized` and `analysis` use the shared collection
    assert all("(tool)" in x and str(study.collection.path) in x for x in external)
    restricted = [x for x in lines if x.startswith("restricted:")]
    assert any(
        "dicoms-a_PrismaFit16001 (source of standardized)" in x for x in restricted
    )  # the instrument data are closed
    # the collection is not copied anywhere: the datasets only carry the pointer to it
    assert (
        git(url(platform, "standardized"), "ls-tree", "-r", "--name-only", "v1").count("images")
        == 0
    )


def test_an_unretrievable_container_revision_stops_the_release(study, platform, monkeypatch):
    import shutil

    shutil.rmtree(Path(study.collection.path) / ".git" / "annex", ignore_errors=True)
    shutil.rmtree(Path(study.collection.path) / ".git", ignore_errors=True)
    out = do_release(platform, monkeypatch, "v1")
    assert out.exit_code == 1
    assert "standardized: container tool of collection containers" in out.output
    assert "no longer served" in out.output and "nothing was tagged" in out.output
    for name in REPOS:
        assert tags(platform, name) == ""


def test_differing_licenses_are_shown_and_do_not_block(study, platform, monkeypatch):
    out = do_release(platform, monkeypatch, "v1")
    assert out.exit_code == 0
    licence = [x for x in out.output.splitlines() if x.startswith("license: standardized")]
    assert len(licence) == 1
    assert "references: dicoms-a_PrismaFit16001" in licence[0] and "(differ)" in licence[0]
    assert "CC-BY-4.0" in licence[0] and "LicenseRef-Restricted" in licence[0]
