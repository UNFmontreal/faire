"""Indexing received files into an instrument's source dataset (direct storage)."""

import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner
from datalad.api import Dataset, clone

from faire import indexing
from faire.cli import main
from faire.platform.fake import FakePlatform

pytestmark = pytest.mark.integration

GROUP = "example-study"
REPO = "dicoms-a_PrismaFit16001"


@pytest.fixture
def platform(tmp_path):
    return FakePlatform(tmp_path / "hosting")


@pytest.fixture
def study(project, platform):
    project.init(platform=platform, group=GROUP)
    return project


def received(tmp_path, files, name="incoming"):
    root = tmp_path / name
    for path, text in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    return root


def request(study, platform, incoming, **kw):
    return indexing.Request(
        incoming,
        "dicoms",
        study.dmp,
        study.site,
        indexing.locator(platform, GROUP, None),
        **kw,
    )


def remote_log(platform, branch="dev", repo=REPO):
    url = platform.get_repository(GROUP, repo).url
    out = subprocess.run(
        ["git", "log", branch, "--format=%B"], cwd=url, capture_output=True, text=True
    )
    return out.stdout


def remote_head(platform, branch="dev", repo=REPO):
    url = platform.get_repository(GROUP, repo).url
    return subprocess.run(
        ["git", "rev-parse", branch], cwd=url, capture_output=True, text=True
    ).stdout.strip()


SAMPLE = {"01/003/a.dcm": "scan a\n", "01/003/b.dcm": "scan b\n"}


# -- 7.2 dry run -------------------------------------------------------------------------------


def test_dry_run_prints_the_decisions_and_changes_nothing(study, platform, tmp_path):
    incoming = received(
        tmp_path,
        {
            **SAMPLE,
            "01/003/phi-report.pdf": "x\n",
            "01/003/.hidden": "x\n",
            "01/003/PILOT": "",
            "01/003/instrument.txt": "PrismaFit16001 XA60\n",
        },
    )
    before = remote_head(platform)
    out = indexing.index(request(study, platform, incoming, dry_run=True))
    assert out.entities == {"subject": "01", "session": "003"}
    assert out.pilot and out.branch == "pilot" and out.software == "XA60"
    assert ("01/003/a.dcm", "01/003/a.dcm", False) in out.kept
    assert ("01/003/phi-report.pdf", "01/003/phi-report.pdf", True) in out.kept
    assert sorted(out.dropped) == ["01/003/.hidden", "01/003/PILOT", "01/003/instrument.txt"]
    assert out.commit is None and not out.pushed
    assert remote_head(platform) == before
    assert remote_head(platform, "pilot") == remote_head(platform, "main")  # nothing on pilot


def test_the_command_in_dry_run_mode_prints_what_the_heuristic_decided(study, platform, tmp_path):
    incoming = received(tmp_path, {**SAMPLE, "01/003/phi.pdf": "x\n"})
    before = remote_head(platform)
    import faire.platform.factory as factory

    factory_connect = factory.connect
    factory.connect = lambda name, url, token=None: platform
    try:
        result = CliRunner().invoke(
            main,
            [
                "index",
                str(incoming),
                "--stream",
                "dicoms",
                "--madmp",
                str(study.madmp),
                "--site",
                "a",
                "--sites-dir",
                str(study.sites_dir),
                "--platform",
                "gitlab",
                "--platform-url",
                "https://example.org",
                "--group",
                GROUP,
                "--dry-run",
            ],
        )
    finally:
        factory.connect = factory_connect
    assert result.exit_code == 0, result.output
    for line in (
        "sample: subject=01,session=003",
        "pilot: no (branch dev)",
        "keep: 01/003/a.dcm -> 01/003/a.dcm",
        "keep: 01/003/phi.pdf -> 01/003/phi.pdf [sensitive]",
        "would: record the sample in a_PrismaFit16001 on dev",
    ):
        assert line in result.output
    assert remote_head(platform) == before


# -- 7.3 direct storage ------------------------------------------------------------------------


def test_new_sample_is_recorded_pushed_and_retrievable_from_the_collection_storage(
    study, platform, tmp_path
):
    incoming = received(tmp_path, {**SAMPLE, "01/003/instrument.txt": "PrismaFit16001 XA60\n"})
    out = indexing.index(request(study, platform, incoming))
    assert out.commit and out.pushed == ["collection-site-storage", "origin"]
    log = remote_log(platform)
    assert "faire-sample: subject=01,session=003" in log
    assert "faire-pilot: false" in log
    assert "faire-software: XA60" in log
    assert "faire-heuristic: " in log and "faire-instrument: PrismaFit16001" in log
    # a fresh clone sees the files and gets their content from the collection storage alone
    fresh = clone(
        platform.get_repository(GROUP, REPO).url,
        str(tmp_path / "fresh"),
        result_renderer="disabled",
    )
    fresh.repo.call_git(["checkout", "dev"])
    from faire import remotes

    spec = remotes.specs(study.dmp.dataset("dicoms"), REPO, study.site, stages=("collection",))[0]
    remotes.enable(fresh, spec)
    fresh.get("01/003/a.dcm", result_renderer="disabled")
    assert (Path(fresh.path) / "01/003/a.dcm").read_text() == "scan a\n"
    assert not (Path(fresh.path) / "01/003/instrument.txt").exists()  # dropped by the heuristic


def test_the_indexing_commit_records_the_heuristic_revision(study, platform, tmp_path):
    out = indexing.index(request(study, platform, received(tmp_path, SAMPLE)))
    log = remote_log(platform)
    revision = [x for x in log.splitlines() if x.startswith("faire-heuristic:")][0].split()[1]
    url = platform.get_repository(GROUP, REPO).url
    touched = subprocess.run(
        ["git", "log", "dev", "-1", "--format=%H", "--", ".faire/heuristic.py"],
        cwd=url,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert revision == touched and out.commit


def test_a_pilot_sample_lands_on_the_pilot_branch_only(study, platform, tmp_path):
    dev, pilot = remote_head(platform), remote_head(platform, "pilot")
    incoming = received(tmp_path, {**SAMPLE, "01/003/PILOT": ""})
    out = indexing.index(request(study, platform, incoming))
    assert out.pilot and out.branch == "pilot"
    assert remote_head(platform) == dev  # dev is untouched
    assert remote_head(platform, "pilot") != pilot
    assert "faire-pilot: true" in remote_log(platform, "pilot")


def stored(folder: Path) -> int:
    """Number of objects a directory special remote holds."""
    return len(
        [p for p in folder.rglob("*") if p.is_file() and "tmp" not in p.relative_to(folder).parts]
    )


def test_sensitive_content_goes_only_to_storage_that_accepts_it(project, platform, tmp_path):
    sensitive_dir = project.add_sensitive_store()
    project.init(platform=platform, group=GROUP)
    incoming = received(tmp_path, {**SAMPLE, "01/003/phi-notes.pdf": "name: X\n"})
    out = indexing.index(request(project, platform, incoming))
    assert sorted(out.pushed) == [
        "collection-sensitive-storage",
        "collection-site-storage",
        "origin",
    ]
    general = project.storage / REPO
    assert stored(general) == 2  # the two scans, not the sensitive file
    assert stored(sensitive_dir / REPO) == 1  # only the sensitive file
    url = platform.get_repository(GROUP, REPO).url
    fresh = clone(url, str(tmp_path / "fresh"), result_renderer="disabled")
    fresh.repo.call_git(["checkout", "dev"])
    marks = subprocess.run(
        ["git", "annex", "metadata", "01/003/phi-notes.pdf"],
        cwd=fresh.path,
        capture_output=True,
        text=True,
    ).stdout
    assert "distribution-restrictions=sensitive" in marks


def test_not_an_instrument_source_dataset_fails_before_changing_anything(study, platform, tmp_path):
    before = remote_head(platform, repo="standardized")
    bad = indexing.Request(
        received(tmp_path, SAMPLE),
        "standardized",
        study.dmp,
        study.site,
        indexing.locator(platform, GROUP, None),
    )
    with pytest.raises(indexing.IndexingError, match="declares no instrument"):
        indexing.index(bad)
    assert remote_head(platform, repo="standardized") == before


def test_a_sample_the_heuristic_cannot_identify_records_nothing(study, platform, tmp_path):
    before = remote_head(platform)
    incoming = received(tmp_path, {"flat.dcm": "x\n"})  # no <subject>/<session>/ folders
    with pytest.raises(indexing.IndexingError, match="expected <subject>/<session>/<file>"):
        indexing.index(request(study, platform, incoming))
    assert remote_head(platform) == before


def test_the_missing_entity_is_named(study, platform, tmp_path):
    # a heuristic that finds no session: replace the reference one in the instance's history
    url = platform.get_repository(GROUP, REPO).url
    work = Dataset(tmp_path / "edit")
    clone(url, str(work.path), result_renderer="disabled")
    work.repo.call_git(["checkout", "dev"])
    (Path(work.path) / ".faire/heuristic.py").write_text(
        'def entities(files, ctx):\n    return {"subject": "01"}\n'
    )
    work.save(message="a heuristic without sessions", result_renderer="disabled")
    work.push(to="origin", data="nothing", result_renderer="disabled")
    before = remote_head(platform)
    with pytest.raises(indexing.IndexingError, match="'session'"):
        indexing.index(request(study, platform, received(tmp_path, SAMPLE)))
    assert remote_head(platform) == before
    assert json.dumps(study.dmp.sample_entities)
