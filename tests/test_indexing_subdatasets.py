"""A sample stored in a subdataset of its own."""

import textwrap
from pathlib import Path

import pytest
from datalad.api import clone

from faire import indexing
from faire.platform.fake import FakePlatform
from indexfix import GROUP, REPO, git, received, request, set_heuristic

pytestmark = pytest.mark.integration

SUB = "sub-01_ses-003"
SUB_REPO = "dicoms-a_PrismaFit16001-sub-01-ses-003"

BASE = textwrap.dedent(
    """
    def entities(files, ctx):
        first = sorted(f.name for f in files)[0].split("/")
        return {"subject": first[0], "session": first[1]}

    def placement(file, ctx, entities):
        return file.name.split("/", 2)[2]  # inside the subdataset

    def subdataset(ctx, entities):
        return f"sub-{entities['subject']}_ses-{entities['session']}"
    """
)
SETUP = textwrap.dedent(
    """
    def setup(dataset, ctx):
        from pathlib import Path
        (Path(dataset.path) / ".gitattributes").write_text(
            "* annex.largefiles=anything\\n"
            ".gitattributes annex.largefiles=nothing\\n"
            "*.json annex.largefiles=nothing\\n"
        )
    """
)
FAILING = "def setup(dataset, ctx):\n    raise RuntimeError('cannot configure')\n"
FILES = {"01/003/a.dcm": "scan a\n", "01/003/meta.json": '{"a": 1}\n'}


@pytest.fixture
def platform(tmp_path):
    return FakePlatform(tmp_path / "hosting")


@pytest.fixture
def study(project, platform):
    project.init(platform=platform, group=GROUP)
    return project


def sub_repo_url(platform):
    return platform.get_repository(GROUP, SUB_REPO).url


def test_a_sample_with_many_files_gets_a_repository_of_its_own(study, platform, tmp_path):
    set_heuristic(platform, tmp_path, BASE)
    out = indexing.index(request(study, platform, received(tmp_path, FILES)))
    # the repository exists on the platform, is protected like the others, and holds the sample
    assert platform.get_repository(GROUP, SUB_REPO) is not None
    assert platform.protected_branches(platform.get_repository(GROUP, SUB_REPO))
    assert out.subdataset == SUB and "origin:" + SUB in out.pushed
    assert "faire-sample: subject=01,session=003" in git(sub_repo_url(platform), "log", "dev")
    # it is registered in the instance at the path the heuristic assigned, pointing at that repo
    url = platform.get_repository(GROUP, REPO).url
    modules = git(url, "show", "dev:.gitmodules")
    assert f"path = {SUB}" in modules and sub_repo_url(platform) in modules
    assert git(url, "ls-tree", "dev", SUB).split()[1] == "commit"
    assert git(url, "ls-tree", "dev", SUB).split()[2] == git(
        sub_repo_url(platform), "rev-parse", "dev"
    )
    # a fresh clone of the instance installs the sample's subdataset with its files
    fresh = clone(url, str(tmp_path / "fresh"), result_renderer="disabled")
    fresh.repo.call_git(["checkout", "dev"])
    fresh.get(SUB, get_data=False, result_renderer="disabled")
    assert (Path(fresh.path) / SUB / "a.dcm").exists() or (
        Path(fresh.path) / SUB / "a.dcm"
    ).is_symlink()


def test_each_storage_of_the_subdataset_takes_the_same_files_as_the_parents(
    project, platform, tmp_path
):
    project.add_sensitive_store()
    project.init(platform=platform, group=GROUP)
    set_heuristic(platform, tmp_path, BASE)
    indexing.index(request(project, platform, received(tmp_path, FILES)))
    sub = clone(sub_repo_url(platform), str(tmp_path / "sub"), result_renderer="disabled")
    sub.repo.call_git(["checkout", "dev"])
    parent = clone(
        platform.get_repository(GROUP, REPO).url,
        str(tmp_path / "parent"),
        result_renderer="disabled",
    )
    parent_wanted = {
        r["name"]: parent.repo.get_preferred_content("wanted", r["name"])
        for r in parent.repo.get_special_remotes().values()
    }
    sub_wanted = {
        r["name"]: sub.repo.get_preferred_content("wanted", r["name"])
        for r in sub.repo.get_special_remotes().values()
    }
    assert sub_wanted == parent_wanted and len(sub_wanted) == 2


def test_a_small_sample_stays_in_the_instance_and_creates_no_repository(study, platform, tmp_path):
    before = set(platform.repos)
    indexing.index(request(study, platform, received(tmp_path, FILES)))
    assert set(platform.repos) == before


def test_callback_configures_the_file_handling_in_a_commit_of_its_own(study, platform, tmp_path):
    set_heuristic(platform, tmp_path, BASE + SETUP)
    indexing.index(request(study, platform, received(tmp_path, FILES)))
    url = sub_repo_url(platform)
    subjects = git(url, "log", "dev", "--reverse", "--format=%s").splitlines()
    assert subjects[0].endswith("new dataset")
    assert subjects[1].startswith("Set up")  # the configuration, apart from the data
    assert subjects[2].startswith("Index sample")
    assert "*.json annex.largefiles=nothing" in git(url, "show", "dev~1:.gitattributes")
    setup_commit = git(url, "rev-list", "--reverse", "dev").splitlines()[1]
    assert git(url, "show", "--name-only", "--format=", setup_commit) == ".gitattributes"
    sub = clone(url, str(tmp_path / "sub"), result_renderer="disabled")
    sub.repo.call_git(["checkout", "dev"])
    assert sub.repo.is_under_annex("a.dcm")  # annexed by the callback's configuration
    assert not sub.repo.is_under_annex("meta.json")  # kept in git by it


def test_without_a_callback_the_subdataset_handles_files_as_the_instance_does(
    study, platform, tmp_path
):
    set_heuristic(platform, tmp_path, BASE)
    indexing.index(request(study, platform, received(tmp_path, FILES)))
    instance = git(platform.get_repository(GROUP, REPO).url, "show", "dev:.gitattributes")
    assert git(sub_repo_url(platform), "show", "dev:.gitattributes") == instance
    sub = clone(sub_repo_url(platform), str(tmp_path / "sub"), result_renderer="disabled")
    sub.repo.call_git(["checkout", "dev"])
    assert sub.repo.is_under_annex("meta.json")  # the instance annexes everything


def test_the_callback_is_not_called_again_for_an_existing_subdataset(study, platform, tmp_path):
    set_heuristic(platform, tmp_path, BASE + SETUP)
    indexing.index(request(study, platform, received(tmp_path, FILES)))
    # more data for the same sample, with a heuristic whose callback would now change the setup
    set_heuristic(
        platform,
        tmp_path,
        BASE + SETUP.replace("*.json annex.largefiles=nothing", "*.json annex.largefiles=anything"),
        name="edit2",
    )
    more = received(tmp_path, {"01/003/b.dcm": "scan b\n"}, name="more")
    out = indexing.index(request(study, platform, more))
    url = sub_repo_url(platform)
    setups = [
        s for s in git(url, "log", "dev", "--format=%s").splitlines() if s.startswith("Set up")
    ]
    assert len(setups) == 1  # not called again
    assert "*.json annex.largefiles=nothing" in git(url, "show", "dev:.gitattributes")
    assert "created the subdataset" not in " ".join(out.actions)
    assert git(url, "ls-tree", "-r", "--name-only", "dev").count("b.dcm") == 1


def test_a_failing_callback_records_and_pushes_nothing(study, platform, tmp_path):
    set_heuristic(platform, tmp_path, BASE + FAILING)
    repos = set(platform.repos)
    parent_before = git(platform.get_repository(GROUP, REPO).url, "rev-parse", "dev")
    with pytest.raises(indexing.IndexingError, match="cannot configure"):
        indexing.index(request(study, platform, received(tmp_path, FILES)))
    assert set(platform.repos) == repos  # no repository was created
    assert git(platform.get_repository(GROUP, REPO).url, "rev-parse", "dev") == parent_before
