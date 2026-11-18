"""Sites exchanging history through a hub."""

from pathlib import Path

import pytest

from fedfix import Site, git, make_hub

pytestmark = pytest.mark.integration


@pytest.fixture
def hub(tmp_path):
    return make_hub(tmp_path)


@pytest.fixture
def first(tmp_path, hub):
    site = Site(tmp_path, "a", hub)
    site.init()
    return site


def test_a_second_site_joins_with_the_first_sites_history_and_its_own_instruments(
    tmp_path, hub, first
):
    first.commit("standardized", "dev", "sub-01.md", "a\n")
    assert all(x.ok for x in first.sync())
    second = Site(tmp_path, "b", hub)
    result = second.init()
    assert any("install standardized from the hub" in a for a in result.actions)
    ds = second.repo("standardized")
    assert git(ds.path, "show", "dev:sub-01.md") == "a"
    # an empty instance for each of its own instruments, none of site a's
    repos = {p.name for p in second.project.ws.repos.iterdir()}
    assert {"dicoms-b_Skyra45012", "dicoms-b_PhysioBox7"} <= repos
    assert "dicoms-a_PrismaFit16001" not in repos


def test_two_sites_converge_through_a_bare_hub_and_an_unchanged_state_commits_nothing(
    tmp_path, hub, first
):
    second = Site(tmp_path, "b", hub)
    first.commit("standardized", "dev", "s1.md", "from a\n")
    first.sync()
    second.init()
    second.commit("standardized", "dev", "s2.md", "from b\n")
    assert all(x.ok for x in second.sync())
    assert all(x.ok for x in first.sync())
    for site in (first, second):
        files = git(site.repo("standardized").path, "ls-tree", "--name-only", "dev")
        assert "s1.md" in files and "s2.md" in files
    heads = {git(x.repo("standardized").path, "rev-parse", "dev") for x in (first, second)}
    assert heads == {git(str(hub / "standardized.git"), "rev-parse", "dev")}
    before = git(first.repo("standardized").path, "rev-list", "--all", "--count")
    again = first.sync()
    assert not any(x.changed for x in again)
    assert git(first.repo("standardized").path, "rev-list", "--all", "--count") == before


def test_a_file_the_template_merges_by_union_keeps_the_rows_of_both_sites(tmp_path, hub, first):
    second = Site(tmp_path, "b", hub)
    first.commit("standardized", "dev", "CHANGES", "base\n")
    first.sync()
    second.init()
    first.commit("standardized", "dev", "CHANGES", "base\nrow a\n")
    second.commit("standardized", "dev", "CHANGES", "base\nrow b\n")
    first.sync()
    assert all(x.ok for x in second.sync())
    merged = git(second.repo("standardized").path, "show", "dev:CHANGES")
    assert "row a" in merged and "row b" in merged


def test_an_unresolvable_conflict_stops_that_dataset_and_leaves_the_hub_alone(tmp_path, hub, first):
    second = Site(tmp_path, "b", hub)
    first.commit("standardized", "dev", "notes.md", "one\n")
    first.sync()
    second.init()
    first.commit("standardized", "dev", "notes.md", "from a\n")
    second.commit("standardized", "dev", "notes.md", "from b\n")
    first.sync()
    hub_head = git(str(hub / "standardized.git"), "rev-parse", "dev")
    mine = git(second.repo("standardized").path, "rev-parse", "dev")
    results = {x.repository: x for x in second.sync()}
    assert results["standardized"].conflicts == ["dev: notes.md"]
    assert results["study"].ok  # the other repositories are still synchronised
    assert git(str(hub / "standardized.git"), "rev-parse", "dev") == hub_head
    assert git(second.repo("standardized").path, "rev-parse", "dev") == mine
    assert git(second.repo("standardized").path, "status", "--porcelain") == ""


# -- source pointers: ancestry, never dates --------------------------------------------------------


def _pointer_case(tmp_path):
    """A source with a base commit and two diverged ones, and the same parent at two sites."""
    from datalad.api import create

    source = create(str(tmp_path / "source"), result_renderer="disabled")
    repo = source.repo
    repo.call_git(["branch", "-M", "dev"])
    commits = {}
    for name in ("base", "one", "two"):
        if name != "base":
            repo.call_git(["checkout", "-q", "-B", name, commits["base"]])
        (Path(source.path) / f"{name}.md").write_text(name)
        source.save(message=name, result_renderer="disabled")
        commits[name] = repo.get_hexsha()
    repo.call_git(["checkout", "-q", "dev"])
    repo.call_git(["merge", "-q", "--no-edit", commits["one"], commits["two"]])
    commits["head"] = repo.get_hexsha()

    from fedfix import make_hub

    hub = make_hub(tmp_path, ("parent",))
    parent = create(str(tmp_path / "p1"), result_renderer="disabled")
    parent.repo.call_git(["branch", "-M", "dev"])
    return source, commits, hub, parent


def _point(ds, sha, message):
    ds.repo.call_git(["update-index", "--add", "--cacheinfo", f"160000,{sha},sourcedata/atlas"])
    ds.repo.call_git(["commit", "-q", "-m", message])


def _two_sites(tmp_path, hub, parent, ours, theirs, start):
    from datalad.api import clone

    from faire import federation, sites

    cfg = sites.parse({"site": "a", "hub": {"url": str(hub)}})
    _point(parent, start, "start")
    federation.exchange(parent, cfg, "parent")
    other = clone(str(hub / "parent.git"), str(tmp_path / "p2"), result_renderer="disabled")
    other.repo.call_git(["remote", "rename", "origin", "hub"])
    other.repo.call_git(["checkout", "-q", "-B", "dev", "hub/dev"])
    _point(parent, ours, "ours")
    _point(other, theirs, "theirs")
    federation.exchange(parent, cfg, "parent")  # the hub now has `ours`
    return other, cfg


def test_a_diverged_source_reference_takes_the_sources_synchronised_head(tmp_path):
    from faire import federation

    source, c, hub, parent = _pointer_case(tmp_path)
    other, cfg = _two_sites(tmp_path, hub, parent, c["one"], c["two"], c["base"])
    resolve = federation.pointer_resolver({"sourcedata/atlas": Path(source.path)})
    out = federation.exchange(other, cfg, "parent", resolve)
    assert out.ok, out.conflicts
    assert git(other.path, "ls-tree", "dev", "sourcedata/atlas").split()[2] == c["head"]


def test_the_descendant_source_reference_wins(tmp_path):
    from faire import federation

    source, c, hub, parent = _pointer_case(tmp_path)
    other, cfg = _two_sites(tmp_path, hub, parent, c["base"], c["one"], c["two"])
    resolve = federation.pointer_resolver({"sourcedata/atlas": Path(source.path)})
    assert federation.exchange(other, cfg, "parent", resolve).ok
    assert git(other.path, "ls-tree", "dev", "sourcedata/atlas").split()[2] == c["one"]


def test_a_reference_that_cannot_be_settled_is_reported_not_guessed(tmp_path):
    from faire import federation

    source, c, hub, parent = _pointer_case(tmp_path)
    other, cfg = _two_sites(tmp_path, hub, parent, c["one"], c["two"], c["base"])
    out = federation.exchange(other, cfg, "parent")  # this site has no copy of the source
    assert out.conflicts == ["dev: sourcedata/atlas"]


def test_received_samples_land_on_dev_without_a_pull_request_or_a_run(tmp_path, hub, first):
    first.commit("standardized", "dev", "s1.md", "from a\n")
    first.sync()
    second = Site(tmp_path, "b", hub)
    second.init()
    second.sync()
    path = second.repo("standardized").path
    assert git(path, "show", "dev:s1.md") == "from a"
    assert set(git(path, "branch", "--format=%(refname:short)").split()) <= {
        "dev",
        "main",
        "pilot",
        "git-annex",
    }
    assert "faire-task" not in git(path, "log", "dev", "--format=%B")  # nothing was run for it


def annexed(site, name, text, sensitive=False):
    ds = site.repo("standardized")
    ds.repo.call_git(["checkout", "-q", "dev"])
    (Path(ds.path) / name).write_text(text)
    ds.save(message=name, result_renderer="disabled")
    if sensitive:
        git(ds.path, "annex", "metadata", "--set", "distribution-restrictions+=sensitive", name)
    return ds


def stored(folder):
    return sorted(
        p.name
        for p in folder.rglob("*")
        if p.is_file() and "tmp" not in p.relative_to(folder).parts
    )


def test_content_goes_to_the_hubs_storage_when_it_has_one_and_never_when_sensitive(tmp_path, hub):
    storage = tmp_path / "hub-content"
    site = Site(tmp_path, "a", hub, storage)
    site.init()
    annexed(site, "open.dat", "open\n")
    annexed(site, "phi.dat", "who\n", sensitive=True)
    assert all(x.ok for x in site.sync())
    assert len(stored(storage / "standardized")) == 1


def test_with_a_git_only_hub_other_sites_see_who_holds_a_file_and_nothing_is_transferred(
    tmp_path, hub, first
):
    ds = annexed(first, "open.dat", "open\n")
    git(ds.path, "annex", "copy", "--to", "review-site-storage", "open.dat")
    first.sync()
    second = Site(tmp_path, "b", hub)
    second.init()
    second.sync()
    where = git(second.repo("standardized").path, "annex", "whereis", "open.dat")
    assert "review-site-storage" in where
    assert not list((hub / "standardized.git").glob("annex/objects/**/*.dat"))  # history only
    assert "hub-storage" not in git(ds.path, "annex", "info", "--fast")


def test_the_sync_command_exchanges_with_the_hub_for_a_dataset_and_for_the_workspace(
    tmp_path, hub, first
):
    from click.testing import CliRunner

    from faire.cli import main

    first.commit("standardized", "dev", "s1.md", "from a\n")
    common = ["--madmp", str(first.project.madmp), "--site", "a"]
    common += ["--sites-dir", str(first.project.sites_dir)]
    one = CliRunner().invoke(
        main,
        ["sync", "--stage", "accepted", "--dataset", first.repo("standardized").path, *common],
    )
    assert one.exit_code == 0, one.output
    assert "standardized: in step with the hub" in one.output
    assert git(str(hub / "standardized.git"), "show", "dev:s1.md") == "from a"
    first.commit("standardized", "dev", "s2.md", "again\n")
    everything = CliRunner().invoke(
        main, ["sync", "--stage", "accepted", "--workspace", str(first.root), *common]
    )
    assert everything.exit_code == 0, everything.output
    assert git(str(hub / "standardized.git"), "show", "dev:s2.md") == "again"


# -- one platform for all sites ------------------------------------------------------------------


def test_one_platform_two_sites_each_sample_is_routed_to_its_sites_runners(tmp_path):
    import json

    from faire import ciplan, planning
    from faire.platform.fake import FakePlatform
    from faire.render import gitlab
    from fedfix import GROUP, share_site_configurations

    platform = FakePlatform(tmp_path / "hosting")
    a, b = Site(tmp_path, "a", None), Site(tmp_path, "b", None)
    share_site_configurations(a, b)
    a.init(platform=platform, group=GROUP)
    result = b.init(platform=platform, group=GROUP)  # the second site joins what the platform has
    assert any("install standardized from" in x for x in result.actions)
    assert platform.get_repository(GROUP, "dicoms-b_Skyra45012") is not None
    assert platform.get_repository(GROUP, "dicoms-a_PrismaFit16001") is not None
    repo = platform.get_repository(GROUP, "standardized")
    tags = json.loads(platform.get_variables(repo)["FAIRE_RUNNER_TAGS"])
    assert tags == {"a": ["site-a"], "b": ["site-b"]}
    # a sample is processed where its files came from
    instances = planning.instances_from(a.project.dmp)["dicoms"]
    where = {
        sample: planning.site_of({f"sourcedata/dicoms/{folder}/x": ""}, "dicoms", instances, "a")
        for sample, folder in (("01", "a_PrismaFit16001"), ("02", "b_Skyra45012"))
    }
    assert where == {"01": "a", "02": "b"}
    plan = ciplan.CiPlan(
        "standardized",
        "dev",
        tuple(
            ciplan.Task(f"process:{s}", "process", {"subject": s}, site, 0, f"feature/{s}")
            for s, site in where.items()
        ),
    )
    jobs = gitlab.render(plan, tags)
    assert {j["tags"][0] for j in jobs.values() if "tags" in j} == {"site-a", "site-b"}


# -- what other sites see of a site's source data --------------------------------------------------


def test_other_sites_see_where_a_source_is_and_at_which_revision_but_not_its_content(
    tmp_path, hub, first
):
    first.sync()
    second = Site(tmp_path, "b", hub)
    second.init()
    second.sync()
    seen = git(
        second.repo("standardized").path, "ls-tree", "main", "sourcedata/dicoms/a_PrismaFit16001"
    )
    instance = first.repo("dicoms-a_PrismaFit16001")
    assert seen.split()[2] == git(instance.path, "rev-parse", "main")  # the revision referenced
    assert "dicoms-a_PrismaFit16001" in git(
        second.repo("standardized").path, "show", "main:.gitmodules"
    )  # and where it is
    # nothing of it is on the hub: its repository and content stay with the site
    assert not (hub / "dicoms-a_PrismaFit16001.git").exists()


def test_a_ma_dmp_revision_merged_on_the_hub_reaches_a_site_by_sync(tmp_path, hub, first):
    import json

    from datalad.api import clone

    first.sync()
    second = Site(tmp_path, "b", hub)
    second.init()
    editor = clone(str(hub / "study.git"), str(tmp_path / "editor"), result_renderer="disabled")
    editor.repo.call_git(["checkout", "-q", "-B", "main", "origin/main"])
    path = Path(editor.path) / "madmp.json"
    document = json.loads(path.read_text())
    document["dmp"]["title"] = "Revised plan"
    path.write_text(json.dumps(document, indent=2) + "\n")
    editor.save(message="revise the plan", result_renderer="disabled")
    editor.repo.call_git(["push", "-q", "origin", "main"])
    assert all(x.ok for x in second.sync())
    study = second.repo("study")
    assert (
        json.loads((Path(study.path) / "madmp.json").read_text())["dmp"]["title"] == "Revised plan"
    )
