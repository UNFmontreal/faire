"""Originals replaced by inline processing and pilot content stay where they were acquired."""

import copy
from pathlib import Path

import pytest
from datalad.api import clone

from faire import execute, indexing, publish, remotes, rules
from faire.platform.fake import FakePlatform
from indexfix import GROUP, git, received, request
from rulefix import RULES, make_derived, write_source

pytestmark = pytest.mark.integration

# a de-identification step that replaces a processed file in place
INLINE = copy.deepcopy(RULES)
INLINE["rules"].append(
    {
        "id": "deface",
        "trigger": {"paths": ["{subject}/processed.txt"]},
        "container": "tool",
        "command": "sh -c 'tr a-z A-Z < {inputs} > {subject}/tmp && mv {subject}/tmp {outputs}'",
        "inputs": [{"pattern": "{subject}/processed.txt", "required": True}],
        "outputs": ["{subject}/processed.txt"],
    }
)


def stored(folder: Path) -> list[str]:
    return sorted(
        p.name
        for p in folder.rglob("*")
        if p.is_file() and "tmp" not in p.relative_to(folder).parts
    )


@pytest.fixture
def world(tmp_path):
    src = write_source(tmp_path / "src", {"01/a.txt": "private name\n"})
    ds = make_derived(tmp_path, src, rules=copy.deepcopy(INLINE), annex=True)
    general, sensitive = tmp_path / "general", tmp_path / "sensitive"
    for name, where, wanted in (
        ("review-general", general, "not metadata=distribution-restrictions=sensitive"),
        ("review-sensitive", sensitive, "metadata=distribution-restrictions=sensitive"),
    ):
        spec = remotes.RemoteSpec(name, "review", "directory", {"directory": str(where)}, wanted)
        remotes.create(ds, spec)
    return ds, general, sensitive


def test_the_original_of_a_replaced_file_is_kept_marked_sensitive_and_never_shared(world):
    ds, general, sensitive = world
    ruleset = rules.load(ds.path)
    execute.run_task(ds, ruleset, "process:subject=01", env={})
    before_deface = ds.repo.get_hexsha()
    out = execute.run_task(ds, ruleset, "deface:subject=01", env={})
    assert out.status == "ran"
    assert (Path(ds.path) / "01/processed.txt").read_text() == "PRIVATE NAME\n"

    # the run record names the original, which carries the sensitive mark
    body = ds.repo.call_git(["log", "-1", "--format=%B"])
    [key] = [x.split()[1] for x in body.splitlines() if x.startswith("faire-original:")]
    marks = (
        ds.repo.call_git(["annex", "metadata", "--key", key])
        if False
        else git(ds.path, "annex", "metadata", "--key", key)
    )
    assert "distribution-restrictions=sensitive" in marks

    publish.push_results(ds, ds.repo.get_active_branch())
    assert stored(sensitive) == [key]  # the original, on the sensitive storage only
    shared = stored(general)
    assert key not in shared
    assert len([name for name in shared if name.endswith(".txt")]) == 1  # the processed version

    # a site operator goes back to the revision before de-identification and gets the original
    fresh = clone(ds.path, str(Path(ds.path).parent / "fresh"), result_renderer="disabled")
    fresh.repo.call_git(["checkout", "-q", before_deface])
    for name, where in (("review-sensitive", sensitive),):
        remotes.enable(
            fresh,
            remotes.RemoteSpec(name, "review", "directory", {"directory": str(where)}, "anything"),
        )
    fresh.get("01/processed.txt", result_renderer="disabled")
    assert (Path(fresh.path) / "01/processed.txt").read_text() == "private name\n"


# -- pilot content stays at the site that acquired it ------------------------------------------


def objects(folder: Path) -> int:
    return len(stored(folder))


def test_pilot_content_reaches_the_site_storage_but_no_other_remote(project, tmp_path):
    external = project.add_external_store()
    platform = FakePlatform(tmp_path / "hosting")
    project.init(platform=platform, group=GROUP)
    site = project.storage / "dicoms-a_PrismaFit16001"
    ext = external / "dicoms-a_PrismaFit16001"

    indexing.index(request(project, platform, received(tmp_path, {"01/003/a.txt": "prod\n"})))
    assert objects(site) == 1 and objects(ext) == 1  # production content goes everywhere
    pilot = {"01/004/a.txt": "pilot data\n", "01/004/PILOT": ""}
    indexing.index(request(project, platform, received(tmp_path, pilot, "p")))
    assert objects(site) == 2  # the site keeps its pilot content
    assert objects(ext) == 1  # and the external storage never received it


def test_the_wanted_rule_of_a_non_site_remote_excludes_pilot_content(project):
    project.add_external_store()
    specs = {
        s.name: s
        for s in remotes.specs(
            project.dmp.dataset("dicoms"), "dicoms-a_PrismaFit16001", project.site
        )
    }
    assert "pilot" not in specs["collection-site-storage"].wanted  # the site's own storage
    assert specs["collection-external-storage"].wanted == (
        "(anything) and not metadata=distribution-restrictions=pilot"
    )


def test_what_is_made_of_pilot_content_is_pilot_content(tmp_path):
    src = write_source(tmp_path / "src", {"01/a.txt": "pilot data\n"}, annex=True)
    git(
        src.path, "annex", "metadata", "--set", "distribution-restrictions+=pilot", "--", "01/a.txt"
    )
    ds = make_derived(tmp_path, src, annex=True)
    execute.run_task(ds, rules.load(ds.path), "process:subject=01", env={})
    marks = git(ds.path, "annex", "metadata", "01/processed.txt")
    assert "distribution-restrictions=pilot" in marks

    # content that does not come from pilot data is not marked
    other = write_source(tmp_path / "other" / "src", {"01/a.txt": "ordinary\n"}, annex=True)
    plain = make_derived(tmp_path / "other", other, annex=True)
    execute.run_task(plain, rules.load(plain.path), "process:subject=01", env={})
    assert "pilot" not in git(plain.path, "annex", "metadata", "01/processed.txt")
