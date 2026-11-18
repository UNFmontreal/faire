"""An indexed sample starts the datasets derived from the source dataset."""

from pathlib import Path

import pytest
from datalad.api import Dataset, clone

from faire import execute, indexing, planning, publish, remotes, rules
from faire.platform import PlatformError
from faire.platform.fake import FakePlatform
from indexfix import GROUP, REPO, received, request

pytestmark = pytest.mark.integration

SAMPLE = {"01/003/scan.txt": "scan\n"}
STD = f"{GROUP}/standardized"


@pytest.fixture
def platform(tmp_path):
    return FakePlatform(tmp_path / "hosting")


def triggers(platform):
    return [p for p in platform.pipelines if p[0] == STD]


def test_the_push_triggers_the_derived_dataset_with_the_sample_entities(
    project, platform, tmp_path
):
    project.init(platform=platform, group=GROUP)
    out = indexing.index(request(project, platform, received(tmp_path, SAMPLE)))
    assert out.triggered == [STD]
    [(_, ref, variables)] = triggers(platform)
    assert ref == "dev"
    assert variables == {
        "FAIRE_UPSTREAM": "dicoms",
        "FAIRE_REVISION": out.commit,
        "FAIRE_SAMPLE": "subject=01,session=003",
    }
    # only datasets that use the stream as a triggering source are started
    assert {p[0] for p in platform.pipelines} == {STD}


def test_a_pilot_sample_starts_the_pilot_branch_pipeline(project, platform, tmp_path):
    project.init(platform=platform, group=GROUP)
    indexing.index(request(project, platform, received(tmp_path, {**SAMPLE, "01/003/PILOT": ""})))
    assert [ref for _, ref, _ in triggers(platform)] == ["pilot"]


def test_nothing_new_triggers_nothing(project, platform, tmp_path):
    project.init(platform=platform, group=GROUP)
    incoming = received(tmp_path, SAMPLE)
    indexing.index(request(project, platform, incoming))
    platform.pipelines.clear()
    again = indexing.index(request(project, platform, incoming))
    assert again.commit is None and not platform.pipelines


def test_a_lost_trigger_is_only_a_warning(project, platform, tmp_path, monkeypatch):
    project.init(platform=platform, group=GROUP)

    def lost(*args, **kwargs):
        raise PlatformError("connection reset")

    monkeypatch.setattr(platform, "trigger_pipeline", lost)
    out = indexing.index(request(project, platform, received(tmp_path, SAMPLE)))
    assert out.commit and not out.triggered
    assert "not triggered" in out.warnings[0] and "connection reset" in out.warnings[0]


def test_the_derived_dataset_opens_a_pull_request_for_the_indexed_sample(
    project, platform, tmp_path
):
    project.init(platform=platform, group=GROUP)
    out = indexing.index(request(project, platform, received(tmp_path, SAMPLE)))
    [(_, ref, variables)] = triggers(platform)

    # what the downstream pipeline does: plan from the state of the dataset, run, deliver
    repo = platform.get_repository(GROUP, "standardized")
    ds = clone(repo.url, str(tmp_path / "standardized"), result_renderer="disabled")
    ds.repo.call_git(["checkout", ref])
    ds.get("sourcedata", get_data=False, recursive=True, result_renderer="disabled")
    # the runner is at the site: it can reach the site's storage
    instance = Dataset(Path(ds.path) / "sourcedata/dicoms/a_PrismaFit16001")
    for spec in remotes.specs(
        project.dmp.dataset("dicoms"), REPO, project.site, stages=("collection",)
    ):
        remotes.enable(instance, spec)
    for spec in remotes.specs(
        project.dmp.dataset("standardized"), "standardized", project.site, stages=("review",)
    ):
        remotes.enable(ds, spec)
    ruleset = rules.load(ds.path)
    due = planning.due_tasks(ds, ruleset, default_site="a", update=True)
    assert [d.sample for d in due] == [{"subject": "01", "session": "003"}]
    assert variables["FAIRE_SAMPLE"] == "subject=01,session=003"
    outcome = execute.run_task(ds, ruleset, due[0].id, update=True, env={})
    assert outcome.status == "ran"
    publish.push_results(ds, outcome.branch)
    pr = publish.open_pull_request(
        platform, repo, outcome.branch, "dev", outcome.branch, [due[0].id], []
    )
    assert pr.source == outcome.branch == planning.branch_of(due[0].sample)
    assert pr.target == "dev"
    assert (Path(ds.path) / "01/003/processed.txt").read_text() == "scan\n"
    assert out.commit
