"""Fulfilling distributions at their stage: `faire sync`."""

import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner
from datalad.api import clone

from faire import distribution, remotes
from faire.cli import main
from faire.platform.fake import FakePlatform
from indexfix import GROUP, git

pytestmark = pytest.mark.integration

NOT_SENSITIVE = "not metadata=distribution-restrictions=sensitive"


@pytest.fixture
def platform(tmp_path):
    return FakePlatform(tmp_path / "hosting")


def objects(folder: Path) -> list[str]:
    inside = [p for p in folder.rglob("*") if p.is_file()]
    return sorted(p.name for p in inside if "tmp" not in p.relative_to(folder).parts)


def content_of(ds, files: dict[str, str], sensitive: tuple[str, ...] = ()):
    for name, text in files.items():
        (Path(ds.path) / name).write_text(text)
    ds.save(message="content", result_renderer="disabled")
    for name in sensitive:
        mark = "distribution-restrictions+=sensitive"
        subprocess.run(
            ["git", "annex", "metadata", "--set", mark, "--", name], cwd=ds.path, check=True
        )


def sync(project, ds, stage, *extra, env=None):
    args = ["sync", "--stage", stage, "--dataset", ds.path, "--madmp", str(project.madmp)]
    args += ["--site", "a", "--sites-dir", str(project.sites_dir), *extra]
    return CliRunner().invoke(main, args, env=env)


class FakeDepositor:
    id_type = "doi"

    def __init__(self):
        self.deposited: list[str] = []
        self.minted = 0

    def deposit(self, dist, files):
        self.deposited += [f.name for f in files]
        return "https://fake.example/deposit/1"

    def mint(self, dist, tag):
        self.minted += 1
        return f"10.0000/fake.{tag}"


def _atlas(project, platform, tmp_path):
    project.release = project.add_stage_distribution(
        "atlas", "release", "Release store", filter=NOT_SENSITIVE
    )
    project.archive = project.add_stage_distribution("atlas", "archival", "Archive", long_term=True)
    project.init(platform=platform, group=GROUP)
    ds = clone(
        platform.get_repository(GROUP, "atlas").url,
        str(tmp_path / "atlas"),
        result_renderer="disabled",
    )
    ds.repo.call_git(["checkout", "-q", "-B", "dev", "origin/dev"])
    return ds


@pytest.fixture
def atlas(project, platform, tmp_path):
    """The atlas dataset in a clone, with release and archival distributions."""
    return _atlas(project, platform, tmp_path)


@pytest.fixture
def deposit(project, platform, tmp_path, monkeypatch):
    """The same, with a release distribution to a host that has no git-annex support."""
    fake = FakeDepositor()
    monkeypatch.setitem(distribution.DEPOSITORS, "Zenodo", fake)
    project.add_stage_distribution("atlas", "release", "Zenodo", method="zenodo")
    fake.dataset = _atlas(project, platform, tmp_path)
    return fake


def test_only_the_distributions_of_the_stage_are_fulfilled(project, atlas):
    content_of(atlas, {"a.txt": "one\n", "b.txt": "two\n"})
    assert not [n for n in remotes.names(atlas) if n.startswith(("release", "archival"))]
    out = sync(project, atlas, "release")
    assert out.exit_code == 0, out.output
    assert "Release store (release-release-store): done, 2 file(s) transferred" in out.output
    assert len(objects(project.release / "atlas")) == 2
    assert not (project.archive / "atlas").exists()  # the archival host was not touched
    assert not [n for n in remotes.names(atlas) if n.startswith("archival")]


def test_the_remote_is_created_on_first_use_with_its_rules_and_reused_after(project, atlas):
    content_of(atlas, {"a.txt": "one\n"})
    first = sync(project, atlas, "release")
    assert "remote created" in first.output
    wanted = atlas.repo.get_preferred_content("wanted", "release-release-store")
    assert NOT_SENSITIVE in wanted and "pilot" in wanted  # outside the site: no pilot content
    content_of(atlas, {"b.txt": "two\n"})
    second = sync(project, atlas, "release")
    assert "remote created" not in second.output and "1 file(s) transferred" in second.output
    assert len(objects(project.release / "atlas")) == 2
    third = sync(project, atlas, "release")  # nothing new: nothing transferred
    assert "0 file(s) transferred" in third.output


def test_a_sensitive_file_is_never_transferred_even_when_marked_later(project, atlas):
    content_of(atlas, {"a.txt": "one\n", "phi.txt": "who\n"}, sensitive=("phi.txt",))
    assert sync(project, atlas, "release").exit_code == 0
    assert len(objects(project.release / "atlas")) == 1  # a.txt alone
    # a file not yet transferred becomes sensitive before the next fulfilment
    content_of(atlas, {"late.txt": "late\n"}, sensitive=("late.txt",))
    assert sync(project, atlas, "release").exit_code == 0
    assert len(objects(project.release / "atlas")) == 1


def test_a_fresh_clone_sees_what_the_host_holds_and_gets_it_from_there(
    project, platform, atlas, tmp_path
):
    content_of(atlas, {"a.txt": "one\n"})
    atlas.push(to="origin", data="nothing", result_renderer="disabled")
    assert sync(project, atlas, "release").exit_code == 0
    fresh = clone(
        platform.get_repository(GROUP, "atlas").url,
        str(tmp_path / "fresh"),
        result_renderer="disabled",
    )
    fresh.repo.call_git(["checkout", "-q", "-B", "dev", "origin/dev"])
    where = git(fresh.path, "annex", "whereis", "a.txt")
    assert "release-release-store" in where
    spec = remotes.specs(project.dmp.dataset("atlas"), "atlas", project.site, stages=("release",))[
        0
    ]
    remotes.enable(fresh, spec)
    fresh.get("a.txt", result_renderer="disabled")
    assert (Path(fresh.path) / "a.txt").read_text() == "one\n"


def test_sync_can_be_limited_to_a_named_distribution(project, atlas):
    mirror = project.add_stage_distribution("atlas", "release", "Mirror")
    content_of(atlas, {"a.txt": "one\n"})
    out = sync(project, atlas, "release", "--distribution", "Mirror")
    assert out.exit_code == 0 and "Mirror" in out.output and "Release store" not in out.output
    assert len(objects(mirror / "atlas")) == 1 and not (project.release / "atlas").exists()


def test_a_missing_secret_fails_that_distribution_alone_without_printing_a_value(
    project, platform, tmp_path
):
    project.add_stage_distribution(
        "atlas", "release", "Secure store", secrets={"token": "SECURE_TOKEN"}
    )
    mirror = project.add_stage_distribution("atlas", "release", "Mirror")
    project.init(platform=platform, group=GROUP)
    ds = clone(
        platform.get_repository(GROUP, "atlas").url,
        str(tmp_path / "atlas"),
        result_renderer="disabled",
    )
    ds.repo.call_git(["checkout", "-q", "-B", "dev", "origin/dev"])
    content_of(ds, {"a.txt": "one\n"})
    out = sync(project, ds, "release", env={"SECURE_TOKEN": ""})
    assert out.exit_code == 1
    assert "Secure store (release-secure-store): failed" in out.output
    assert "SECURE_TOKEN" in out.output
    assert len(objects(mirror / "atlas")) == 1  # the other distribution was still attempted
    value = "value-that-must-never-be-printed"
    again = sync(project, ds, "release", env={"SECURE_TOKEN": value})
    assert again.exit_code == 0 and value not in again.output


# -- 9.4 completeness, 9.5 deposit hosts, 9.6 write-back, 9.7 resuming ---------------------------


@pytest.fixture
def study(project, platform, tmp_path):
    ds = clone(
        platform.get_repository(GROUP, "study").url,
        str(tmp_path / "study"),
        result_renderer="disabled",
    )
    return ds


def releases(study, dataset_id="atlas"):
    from faire import model

    return model.load(Path(study.path) / "madmp.json").dataset(dataset_id).releases


def test_incomplete_outcomes_obtain_no_identifier_and_record_nothing(project, atlas, study):
    wanted = [distribution.Outcome("Release store", "incomplete", "1 file", "r", missing=["a"])]
    dataset = project.dmp.dataset("atlas")
    lines = distribution.complete(atlas, dataset, "release", wanted, study, "v1")
    assert lines[0].startswith("incomplete") and releases(study) == []


def test_a_deposit_host_gets_its_files_and_the_identifier_is_recorded_once(project, deposit, study):
    atlas = deposit.dataset
    content_of(atlas, {"a.txt": "one\n"})
    for _ in range(2):  # the second run is a repeat
        out = sync(project, atlas, "release", "--tag", "v1", "--study", study.path)
        assert out.exit_code == 0, out.output
    assert deposit.minted == 1, out.output
    (record,) = releases(study)
    assert record["id"] == "v1" and record["revision"] == atlas.repo.get_hexsha()
    assert [i["identifier"] for i in record["identifiers"]] == ["10.0000/fake.v1"]


def test_the_write_back_is_a_validated_commit_by_the_automation_identity(project, deposit, study):
    atlas = deposit.dataset
    content_of(atlas, {"a.txt": "one\n"})
    env = {"FAIRE_AUTOMATION_NAME": "bot", "FAIRE_AUTOMATION_EMAIL": "bot@example.org"}
    assert (
        sync(project, atlas, "release", "--tag", "v1", "--study", study.path, env=env).exit_code
        == 0
    )
    remote = platform_head_author(study)
    assert remote == "bot <bot@example.org>"
    from faire import model, validate

    dmp = model.load(Path(study.path) / "madmp.json")
    assert validate.validate(dmp.document) == []
    dists = {d.title: d.raw for d in dmp.dataset("atlas").distributions}
    assert dists["Zenodo"]["access_url"] == "https://fake.example/deposit/1"
    assert dists["Release store"]["byte_size"] > 0 and dists["Release store"]["issued"]


def platform_head_author(study):
    return git(study.path, "log", "-1", "--format=%an <%ae>", "origin/main")


def test_an_interrupted_fulfilment_completes_by_transferring_only_what_is_missing(project, atlas):
    content_of(atlas, {"a.txt": "one\n", "b.txt": "two\n"})
    assert sync(project, atlas, "release").exit_code == 0
    stored = sorted(objects(project.release / "atlas"))
    victim = next(
        p for p in (project.release / "atlas").rglob("*") if p.is_file() and p.name == stored[0]
    )
    victim.parent.chmod(0o755)
    victim.chmod(0o644)
    victim.unlink()  # as if the transfer had stopped half way
    git(atlas.path, "annex", "fsck", "--fast", "--from", "release-release-store")
    out = sync(project, atlas, "release")
    assert out.exit_code == 0 and "1 file(s) transferred" in out.output
    assert sorted(objects(project.release / "atlas")) == stored
