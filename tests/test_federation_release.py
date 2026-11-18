"""A release across sites: started by the coordinator, delivered by each site, completed by it."""

from pathlib import Path

import pytest
from datalad.api import clone

from faire import distribution, federation, model
from fedfix import Site, git, make_hub

pytestmark = pytest.mark.integration


class Minting:
    """A host that gives out identifiers for what it holds (git-annex reaches it for content)."""

    id_type = "doi"

    def __init__(self):
        self.minted = 0

    def mint(self, dist, tag):
        self.minted += 1
        return f"10.0000/fake.{tag}"


@pytest.fixture
def sites(tmp_path):
    hub = make_hub(tmp_path)
    release, archive = tmp_path / "release-store", tmp_path / "archive"
    a, b = Site(tmp_path, "a", hub), Site(tmp_path, "b", hub)
    for one in (a, b):
        one.release_to(release, archive)
    a.init()
    a.sync()  # the first site publishes; the second joins from the hub
    b.init()
    for one, name in ((a, "a1.dat"), (b, "b1.dat")):
        one.annexed(name, f"{name}\n")
    for one in (a, b, a):
        assert all(x.ok for x in one.sync())
    return a, b


def study_clone(tmp_path, hub):
    return clone(str(hub / "study.git"), str(tmp_path / "study-clone"), result_renderer="disabled")


def start(site, tag="v1"):
    return federation.start_release(site.root, site.project.dmp, site.project.site, tag)


def test_only_the_coordinator_starts_a_release(sites):
    a, b = sites
    with pytest.raises(federation.FederationError, match="only 'a'"):
        start(b)
    assert not start(a).refused


def test_a_site_not_yet_on_the_hub_stops_the_release_and_is_named(sites):
    a, b = sites
    for one, text in ((a, "from a\n"), (b, "from b\n")):
        one.commit("standardized", "dev", "notes.md", text)
    a.sync()
    assert not all(x.ok for x in b.sync())  # b's merge conflicts: its work is not on the hub
    report = start(a)
    assert report.refused and report.problems == ["site b has accepted work the hub does not hold"]
    assert "v1" not in git(str(a.project.hub["url"] + "/standardized.git"), "tag", "--list")


def test_identifiers_are_obtained_only_after_both_sites_delivered_by_the_coordinator_alone(
    tmp_path, sites, monkeypatch
):
    a, b = sites
    minting = Minting()
    monkeypatch.setitem(distribution.DEPOSITORS, "Release store", minting)
    assert not start(a).refused
    hub = Path(a.project.hub["url"])
    study = study_clone(tmp_path, hub)
    dmp, config = a.project.dmp, a.project.site

    federation.deliver(a.root, dmp, config, "v1")  # b has not delivered yet
    first = federation.finish(a.root, dmp, config, "v1", study)
    assert any("owed by b" in line for line in first) and minting.minted == 0
    assert model.load(Path(study.path) / "madmp.json").dataset("standardized").releases == []

    federation.deliver(b.root, b.project.dmp, b.project.site, "v1")
    with pytest.raises(federation.FederationError):
        federation.finish(b.root, b.project.dmp, b.project.site, "v1", study)  # not the coordinator
    federation.finish(a.root, dmp, config, "v1", study)
    (record,) = model.load(Path(study.path) / "madmp.json").dataset("standardized").releases
    assert record["id"] == "v1" and minting.minted == 1
    assert git(study.path, "log", "-1", "--format=%an") == "faire-automation"
    # the sites made no commit of their own to the ma-DMP
    assert "Record release" not in git(b.repo("study").path, "log", "--format=%s")


def test_federated_archival_completes_only_after_both_sites_delivered(tmp_path, sites):
    a, b = sites
    assert not start(a).refused
    dmp, config = a.project.dmp, a.project.site
    study = study_clone(tmp_path, Path(a.project.hub["url"]))
    federation.deliver(a.root, dmp, config, "v1", "archival")
    first = federation.finish(a.root, dmp, config, "v1", study, "archival")
    assert any("owed by b" in line for line in first)
    assert not any(line.startswith("recorded") for line in first)
    federation.deliver(b.root, b.project.dmp, b.project.site, "v1", "archival")
    last = federation.finish(a.root, dmp, config, "v1", study, "archival")
    assert any(line.startswith("recorded in the ma-DMP: Archive") for line in last)
    archive = model.load(Path(study.path) / "madmp.json").dataset("standardized")
    assert all(d.raw.get("byte_size", 0) > 0 for d in archive.distributions if d.title == "Archive")


def test_two_site_study_from_acceptance_to_a_release_with_files_from_both(tmp_path, sites):
    """Each site accepted one sample and both synchronised (the fixture); the coordinator
    releases, each site delivers its own file, and the release completes with both."""
    a, b = sites
    dmp, config = a.project.dmp, a.project.site
    assert not start(a).refused
    study = study_clone(tmp_path, Path(a.project.hub["url"]))
    for one in (a, b):
        federation.deliver(one.root, one.project.dmp, one.project.site, "v1")
    federation.finish(a.root, dmp, config, "v1", study)
    store = tmp_path / "release-store" / "standardized"
    delivered = [
        p for p in store.rglob("*") if p.is_file() and "tmp" not in p.relative_to(store).parts
    ]
    assert len(delivered) == 2  # a1.dat from site a, b1.dat from site b
    (record,) = model.load(Path(study.path) / "madmp.json").dataset("standardized").releases
    assert record["id"] == "v1"
