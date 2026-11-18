"""Samples from an instrument the ma-DMP does not declare."""

import json
from pathlib import Path

import pytest
from datalad.api import clone

from faire import indexing, planning, rules, undeclared
from faire.platform.fake import FakePlatform
from indexfix import GROUP, git, received, request

pytestmark = pytest.mark.integration

NEW = "dicoms-a_PrismaFit16002"
STD = f"{GROUP}/standardized"
BRANCH = "register/a_PrismaFit16002"


def sample(session, instrument="PrismaFit16002"):
    return {f"01/{session}/a.txt": f"scan {session}\n", f"01/{session}/instrument.txt": instrument}


@pytest.fixture
def platform(tmp_path):
    return FakePlatform(tmp_path / "hosting")


@pytest.fixture
def study(project, platform):
    project.init(platform=platform, group=GROUP)
    return project


def merge_registration(platform, tmp_path):
    """What a reviewer does: merge the registration branch into `dev` of the derived dataset."""
    url = platform.get_repository(GROUP, "standardized").url
    work = clone(url, str(tmp_path / "merge"), result_renderer="disabled")
    work.repo.call_git(["checkout", "-q", "-B", "dev", "origin/dev"])
    work.repo.call_git(["merge", "--no-ff", "-q", "-m", "merge registration", f"origin/{BRANCH}"])
    work.repo.call_git(["push", "origin", "dev"])


def test_first_sample_creates_the_instance_and_asks_the_derived_dataset_to_register_it(
    study, platform, tmp_path
):
    out = indexing.index(request(study, platform, received(tmp_path, sample("003"))))
    assert out.undeclared and out.instance == "a_PrismaFit16002"
    assert "PrismaFit16002" in out.warnings[0] and "not declared" in out.warnings[0]
    # the instance exists and holds the sample, with the same template and storage as the others
    repo = platform.get_repository(GROUP, NEW)
    assert repo is not None
    assert "faire-sample: subject=01,session=003" in git(repo.url, "log", "dev", "--format=%B")
    old = platform.get_repository(GROUP, "dicoms-a_PrismaFit16001")
    assert git(repo.url, "show", "dev:.faire/heuristic.py") == git(
        old.url, "show", "dev:.faire/heuristic.py"
    )
    assert platform.protected_branches(repo) == platform.protected_branches(old)
    assert (study.storage / NEW).is_dir()  # its own folder in the site's storage
    # the derived dataset has a pull request registering it, and no other dataset does
    std = platform.get_repository(GROUP, "standardized")
    [pr] = platform.pull_requests(std)
    assert (pr.source, pr.target) == (BRANCH, "dev")
    tree = git(std.url, "ls-tree", "-r", "--name-only", BRANCH)
    assert "sourcedata/dicoms/a_PrismaFit16002" in tree
    assert "sourcedata/dicoms/a_PrismaFit16002" not in git(
        std.url, "ls-tree", "-r", "--name-only", "dev"
    )
    assert not platform.pull_requests(platform.get_repository(GROUP, "analysis"))


def test_samples_wait_for_the_registration(study, platform, tmp_path):
    first = indexing.index(request(study, platform, received(tmp_path, sample("003"), "one")))
    second = indexing.index(request(study, platform, received(tmp_path, sample("004"), "two")))
    assert first.triggered == second.triggered == []
    assert not [p for p in platform.pipelines if p[0] == STD]
    assert "not declared" in second.warnings[0]  # warned at each run
    # still one registration, not one per sample
    assert len(platform.pull_requests(platform.get_repository(GROUP, "standardized"))) == 1
    # and the derived dataset plans nothing for either sample
    ds = clone(
        platform.get_repository(GROUP, "standardized").url,
        str(tmp_path / "std"),
        result_renderer="disabled",
    )
    ds.repo.call_git(["checkout", "dev"])
    ds.get("sourcedata", get_data=False, recursive=True, result_renderer="disabled")
    due = planning.due_tasks(ds, rules.load(ds.path), default_site="a", update=True)
    assert (
        [d.sample.get("session") for d in due] == ["003"]
        or due == []
        or all(d.sample["session"] not in ("003", "004") for d in due)
    )


def test_merging_the_registration_triggers_the_waiting_samples_and_proposes_the_instrument(
    study, platform, tmp_path
):
    for session, name in (("003", "one"), ("004", "two")):
        indexing.index(request(study, platform, received(tmp_path, sample(session), name)))
    merge_registration(platform, tmp_path)

    # the derived dataset's pipeline on `dev`: the samples indexed meanwhile are now due
    std = platform.get_repository(GROUP, "standardized")
    ds = clone(std.url, str(tmp_path / "std"), result_renderer="disabled")
    ds.repo.call_git(["checkout", "-q", "-B", "dev", "origin/dev"])
    ds.get("sourcedata", get_data=False, recursive=True, result_renderer="disabled")
    due = planning.due_tasks(ds, rules.load(ds.path), default_site="a", update=True)
    assert {d.sample["session"] for d in due} == {"003", "004"}

    # and the study gets a pull request adding the instrument to the ma-DMP
    opened = undeclared.propose_instruments(ds, platform, GROUP, tmp_path / "madmp")
    assert [(p.source, p.target) for p in opened] == [("instrument/PrismaFit16002", "main")]
    study_repo = platform.get_repository(GROUP, "study")
    document = json.loads(git(study_repo.url, "show", "instrument/PrismaFit16002:madmp.json"))
    dicoms = next(
        d for d in document["dmp"]["dataset"] if d["dataset_id"]["identifier"] == "dicoms"
    )
    added = [
        r for r in dicoms["technical_resource"] if r["faire"]["instrument_id"] == "PrismaFit16002"
    ]
    assert added and added[0]["faire"]["site"] == "a"
    assert "PrismaFit16002" not in git(study_repo.url, "show", "main:madmp.json")  # not merged yet
    # asking again changes nothing
    again = undeclared.propose_instruments(ds, platform, GROUP, tmp_path / "madmp2")
    assert len(platform.pull_requests(study_repo)) == 1 and len(again) == 1


def test_after_the_registration_new_samples_trigger_the_derived_dataset(study, platform, tmp_path):
    indexing.index(request(study, platform, received(tmp_path, sample("003"), "one")))
    merge_registration(platform, tmp_path)
    out = indexing.index(request(study, platform, received(tmp_path, sample("004"), "two")))
    assert out.triggered == [STD]
    assert [p[0] for p in platform.pipelines] == [STD]


def test_dry_run_reports_the_instance_it_would_create_and_changes_nothing(
    study, platform, tmp_path
):
    repos = set(platform.repos)
    out = indexing.index(request(study, platform, received(tmp_path, sample("003")), dry_run=True))
    assert out.undeclared and any("create the instance" in a for a in out.actions)
    assert set(platform.repos) == repos and not Path(tmp_path / "hosting" / "x").exists()


def test_the_registrations_command_proposes_the_instrument_on_dev_only(
    study, platform, tmp_path, monkeypatch
):
    from click.testing import CliRunner

    from faire.cli import main
    from faire.platform import factory

    indexing.index(request(study, platform, received(tmp_path, sample("003"))))
    merge_registration(platform, tmp_path)
    std = platform.get_repository(GROUP, "standardized")
    ds = clone(std.url, str(tmp_path / "std"), result_renderer="disabled")
    monkeypatch.setattr(factory, "connect", lambda name, url, token=None: platform)
    args = ["registrations", "--dataset", ds.path, "--platform-url", "https://x", "--group", GROUP]
    ds.repo.call_git(["checkout", "-q", "-B", "feature/x", "origin/dev"])
    off = CliRunner().invoke(main, args)
    assert off.exit_code == 0 and "not on dev" in off.output
    assert not platform.pull_requests(platform.get_repository(GROUP, "study"))
    ds.repo.call_git(["checkout", "-q", "-B", "dev", "origin/dev"])
    on = CliRunner().invoke(main, args)
    assert on.exit_code == 0 and "pull request on the study" in on.output
    assert len(platform.pull_requests(platform.get_repository(GROUP, "study"))) == 1
