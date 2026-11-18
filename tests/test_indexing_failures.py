"""Push order, failing storage, and completing an interrupted run."""

import shutil
import textwrap

import pytest

from faire import indexing
from faire.platform.fake import FakePlatform
from indexfix import GROUP, REPO, git, received, request, set_heuristic

pytestmark = pytest.mark.integration

SUB_REPO = "dicoms-a_PrismaFit16001-sub-01-ses-003"
SAMPLE = {"01/003/a.dcm": "scan a\n", "01/003/b.dcm": "scan b\n", "01/003/phi.pdf": "who\n"}
SUBDATASET = textwrap.dedent(
    """
    def entities(files, ctx):
        first = sorted(f.name for f in files)[0].split("/")
        return {"subject": first[0], "session": first[1]}

    def placement(file, ctx, entities):
        return file.name.split("/", 2)[2]

    def sensitive(file, ctx):
        return file.name.endswith(".pdf")

    def subdataset(ctx, entities):
        return f"sub-{entities['subject']}_ses-{entities['session']}"
    """
)


@pytest.fixture
def platform(tmp_path):
    return FakePlatform(tmp_path / "hosting")


def refs(platform, repo=REPO):
    url = platform.get_repository(GROUP, repo).url
    return git(url, "for-each-ref", "--format=%(refname) %(objectname)")


def break_storage(folder):
    """A storage that cannot be written: its folder is replaced by a file."""
    shutil.rmtree(folder)
    folder.write_text("not a directory\n")


def repair_storage(folder):
    folder.unlink()
    folder.mkdir()


def test_no_history_is_pushed_when_the_storage_is_unavailable(project, platform, tmp_path):
    project.init(platform=platform, group=GROUP)
    before = refs(platform)
    break_storage(project.storage / REPO)
    with pytest.raises(indexing.IndexingError, match="collection-site-storage"):
        indexing.index(request(project, platform, received(tmp_path, SAMPLE)))
    assert refs(platform) == before  # neither the branch nor the git-annex branch moved


def test_content_first_then_the_subdataset_then_the_parent(
    project, platform, tmp_path, monkeypatch
):
    project.init(platform=platform, group=GROUP)
    set_heuristic(platform, tmp_path, SUBDATASET)
    order = []
    transfer, push = indexing._transfer, indexing._push_history

    def spy_transfer(ds, specs, result):
        order.append("content")
        transfer(ds, specs, result)

    monkeypatch.setattr(indexing, "_transfer", spy_transfer)

    def spy_push(ds, label, result):
        order.append(label)
        push(ds, label, result)

    monkeypatch.setattr(indexing, "_push_history", spy_push)
    indexing.index(request(project, platform, received(tmp_path, SAMPLE)))
    assert order == ["content", "origin:sub-01_ses-003", "origin"]


def test_a_failing_subdataset_storage_pushes_nothing_and_creates_no_repository(
    project, platform, tmp_path
):
    project.init(platform=platform, group=GROUP)
    set_heuristic(platform, tmp_path, SUBDATASET)
    repos, before = set(platform.repos), refs(platform)
    # the sub-dataset's storage is the sibling of the instance's: make the folder unusable
    (project.storage / SUB_REPO).parent.mkdir(exist_ok=True)
    (project.storage / SUB_REPO).write_text("in the way\n")
    with pytest.raises(indexing.IndexingError, match="collection-site-storage"):
        indexing.index(request(project, platform, received(tmp_path, SAMPLE)))
    assert set(platform.repos) == repos and refs(platform) == before


def test_an_interrupted_run_is_completed_by_running_it_again(project, platform, tmp_path):
    sensitive_dir = project.add_sensitive_store()
    project.init(platform=platform, group=GROUP)
    incoming = received(tmp_path, SAMPLE)
    before = refs(platform)
    # the general storage takes its files, then the sensitive one fails: the run stops
    break_storage(sensitive_dir / REPO)
    with pytest.raises(indexing.IndexingError, match="collection-sensitive-storage"):
        indexing.index(request(project, platform, incoming))
    assert refs(platform) == before
    repair_storage(sensitive_dir / REPO)
    out = indexing.index(request(project, platform, incoming))
    assert out.commit and "origin" in out.pushed
    url = platform.get_repository(GROUP, REPO).url
    log = git(url, "log", "dev", "--format=%B")
    assert log.count("faire-sample: subject=01,session=003") == 1  # the sample appears once
    # and a further run finds it complete
    complete = refs(platform)
    again = indexing.index(request(project, platform, incoming))
    assert again.commit is None and "already indexed" in " ".join(again.actions)
    assert refs(platform) == complete  # the dataset is unchanged
    assert git(url, "rev-parse", "dev")
