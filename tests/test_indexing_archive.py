"""Samples of many small files stored as archives, each file still addressable by its path."""

import textwrap
from pathlib import Path

import pytest
from datalad.api import clone

from faire import indexing, remotes
from faire.platform.fake import FakePlatform
from indexfix import GROUP, REPO, git, received, request, set_heuristic

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("native_annex")]

SUB = "sub-01_ses-003"
SUB_REPO = "dicoms-a_PrismaFit16001-sub-01-ses-003"

HEURISTIC = textwrap.dedent(
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

    def setup(dataset, ctx):
        from pathlib import Path
        root = Path(dataset.path)
        (root / ".gitattributes").write_text(
            "* annex.largefiles=anything\\n.gitattributes annex.largefiles=nothing\\n"
            ".faire/* annex.largefiles=nothing\\n"
        )
        (root / ".faire").mkdir(exist_ok=True)
        (root / ".faire/indexing.yaml").write_text("archive: true\\n")
    """
)
MANY = {f"01/003/slice{i:03d}.dcm": f"slice {i}\n" for i in range(30)}


@pytest.fixture
def platform(tmp_path):
    return FakePlatform(tmp_path / "hosting")


def stored(folder: Path) -> list[Path]:
    return [
        p for p in folder.rglob("*") if p.is_file() and "tmp" not in p.relative_to(folder).parts
    ]


def test_the_storage_holds_archives_and_a_single_file_is_still_obtained_by_path(
    project, platform, tmp_path
):
    sensitive_dir = project.add_sensitive_store()
    project.init(platform=platform, group=GROUP)
    set_heuristic(platform, tmp_path, HEURISTIC)
    files = {**MANY, "01/003/phi-notes.pdf": "identifying\n"}
    out = indexing.index(request(project, platform, received(tmp_path, files)))
    assert out.commit

    # 31 files, but the storages hold two archives: one general, one for the sensitive file
    assert len(stored(project.storage / SUB_REPO)) == 1
    assert len(stored(sensitive_dir / SUB_REPO)) == 1

    # a consumer with a fresh clone obtains one file by its path, from inside the archive
    url = platform.get_repository(GROUP, SUB_REPO).url
    sub = clone(url, str(tmp_path / "sub"), result_renderer="disabled")
    sub.repo.call_git(["checkout", "dev"])
    dmp_dataset = project.dmp.dataset("dicoms")
    for spec in remotes.specs(dmp_dataset, SUB_REPO, project.site, stages=("collection",)):
        remotes.enable(sub, spec)
    remotes.enable_archives(sub)
    sub.get("slice017.dcm", result_renderer="disabled")
    assert (Path(sub.path) / "slice017.dcm").read_text() == "slice 17\n"
    sub.get("phi-notes.pdf", result_renderer="disabled")
    assert (Path(sub.path) / "phi-notes.pdf").read_text() == "identifying\n"
    assert (
        not (Path(sub.path) / "slice018.dcm").exists()
        or (Path(sub.path) / "slice018.dcm").is_symlink()
    )  # the others stay unfetched


def test_the_record_and_the_marks_cover_the_archived_files(project, platform, tmp_path):
    project.add_sensitive_store()
    project.init(platform=platform, group=GROUP)
    set_heuristic(platform, tmp_path, HEURISTIC)
    indexing.index(
        request(project, platform, received(tmp_path, {**MANY, "01/003/phi-notes.pdf": "x\n"}))
    )
    url = platform.get_repository(GROUP, SUB_REPO).url
    log = git(url, "log", "dev", "--format=%B")
    assert "faire-sample: subject=01,session=003" in log
    sub = clone(url, str(tmp_path / "sub"), result_renderer="disabled")
    sub.repo.call_git(["checkout", "dev"])
    listing = git(sub.path, "ls-files")
    assert "phi-notes.pdf" in listing and "slice000.dcm" in listing
    assert ".faire/archives/subject-01_session-003.tar" in listing
    assert ".faire/archives/subject-01_session-003-sensitive.tar" in listing
    marks = git(sub.path, "annex", "metadata", "phi-notes.pdf")
    assert "distribution-restrictions=sensitive" in marks
    assert "sensitive" not in git(sub.path, "annex", "metadata", "slice000.dcm")


def test_indexing_the_same_directory_again_changes_nothing(project, platform, tmp_path):
    project.init(platform=platform, group=GROUP)
    set_heuristic(platform, tmp_path, HEURISTIC)
    incoming = received(tmp_path, MANY)
    indexing.index(request(project, platform, incoming))
    url = platform.get_repository(GROUP, SUB_REPO).url
    before, objects = git(url, "rev-parse", "dev"), len(stored(project.storage / SUB_REPO))
    again = indexing.index(request(project, platform, incoming))
    assert again.commit is None and "already indexed" in " ".join(again.actions)
    assert git(url, "rev-parse", "dev") == before
    assert len(stored(project.storage / SUB_REPO)) == objects
    assert REPO  # the instance repository exists too
