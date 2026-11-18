"""Container collections installed as subdatasets and containers frozen into the dataset."""

import json
import subprocess
from pathlib import Path

import pytest
import yaml
from datalad.api import Dataset, clone, containers_list, create, rerun

from faire import containers
from rulefix import Collection

pytestmark = pytest.mark.integration


def declare(ds, collections, container_list):
    path = Path(ds.path) / containers.DECLARATION
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"collections": collections, "containers": container_list}))
    ds.save(message="declare containers", result_renderer="disabled")


def entry(col, name="lab", path="code/containers", rev=None, source=None):
    return {
        "name": name,
        "source": source or col.path,
        "path": path,
        "revision": rev or col.ds.repo.get_hexsha(),
    }


def head(path):
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=path, capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture
def ds(tmp_path):
    return create(str(tmp_path / "ds"), result_renderer="disabled")


# -- 3.5 the declaration ------------------------------------------------------------------------


def test_declaration_with_two_collections_loads():
    declaration = containers.parse(
        {
            "collections": [
                {"name": "lab", "source": "/a", "path": "c/lab", "revision": "r1"},
                {"name": "repronim", "source": "/b", "path": "c/repronim", "revision": "r2"},
            ],
            "containers": [
                {"name": "mriqc", "collection": "repronim", "version": "0.16.1"},
                {"name": "tool", "collection": "lab", "version": "1.0", "call_fmt": "sh {cmd}"},
            ],
        }
    )
    assert [c.path for c in declaration.collections] == ["c/lab", "c/repronim"]
    assert declaration.containers[1].call_fmt == "sh {cmd}"
    assert declaration.collection("repronim").revision == "r2"


def test_container_naming_an_unknown_collection_is_rejected():
    with pytest.raises(containers.ContainerError, match="'nope' is not declared"):
        containers.parse(
            {
                "collections": [{"name": "lab", "source": "/a", "path": "c", "revision": "r"}],
                "containers": [{"name": "tool", "collection": "nope", "version": "1"}],
            }
        )


@pytest.mark.parametrize(
    "raw, message",
    [
        ({"collections": [{"name": "lab", "source": "/a", "path": "c"}]}, "revision required"),
        (
            {"collections": [{"name": "l", "source": "/a", "path": "../x", "revision": "r"}]},
            "must stay inside",
        ),
        (
            {
                "collections": [{"name": "l", "source": "/a", "path": "c", "revision": "r"}],
                "containers": [{"name": "t", "collection": "l"}],
            },
            "version required",
        ),
    ],
)
def test_incomplete_declarations_are_rejected(raw, message):
    with pytest.raises(containers.ContainerError, match=message):
        containers.parse(raw)


def test_registry_urls_are_no_longer_a_container_declaration():
    # a container comes from a collection; there is no url to pin by digest any more
    with pytest.raises(containers.ContainerError, match="collection required"):
        containers.parse({"containers": [{"name": "t", "url": "docker://x", "version": "1"}]})


# -- 3.6 collections as subdatasets ---------------------------------------------------------------


def test_collection_installed_at_its_path_and_pinned_revision(tmp_path, ds):
    col = Collection(tmp_path / "col")
    first = col.add("tool", "1.0")
    col.add("tool", "2.0")  # the collection has moved on
    declare(ds, [entry(col, rev=first)], [])
    containers.register(ds)
    sub = Path(ds.path) / "code/containers"
    assert head(sub) == first
    subs = ds.subdatasets(result_renderer="disabled", return_type="list")
    assert [Path(s["path"]).relative_to(ds.path).as_posix() for s in subs] == ["code/containers"]
    assert subs[0]["gitshasum"] == first  # the dataset records the pinned revision


def test_two_collections_at_different_paths(tmp_path, ds):
    one, two = Collection(tmp_path / "one"), Collection(tmp_path / "two")
    one.add("tool", "1.0")
    two.add("other", "3.0")
    declare(
        ds,
        [entry(one, "lab", "c/lab"), entry(two, "extra", "c/extra")],
        [
            {"name": "tool", "collection": "lab", "version": "1.0"},
            {"name": "other", "collection": "extra", "version": "3.0"},
        ],
    )
    assert sorted(containers.register(ds)) == ["other", "tool"]
    assert (Path(ds.path) / "c/lab/.git").exists() and (Path(ds.path) / "c/extra/.git").exists()


def test_collection_revision_that_does_not_exist_names_the_collection(tmp_path, ds):
    col = Collection(tmp_path / "col")
    col.add("tool", "1.0")
    declare(ds, [entry(col, rev="0" * 40)], [])
    with pytest.raises(containers.ContainerError, match="collection 'lab'"):
        containers.register(ds)


# -- 3.7 freezing -------------------------------------------------------------------------------


def test_frozen_container_is_listed_and_survives_the_collection_moving_on(tmp_path, ds):
    col = Collection(tmp_path / "col", call_fmt="sh {img} {cmd}")
    first = col.add("tool", "1.0")
    declare(ds, [entry(col, rev=first)], [{"name": "tool", "collection": "lab", "version": "1.0"}])
    containers.register(ds)
    listed = containers_list(dataset=ds, result_renderer="disabled")
    assert [r["name"] for r in listed] == ["tool"]
    assert Path(listed[0]["path"]).relative_to(ds.path).as_posix() == (
        "code/containers/images/tool--1.0.sif"
    )
    assert listed[0]["cmdexec"] == "sh {img} {cmd}"  # copied from the collection's entry
    log = ds.repo.call_git(["log", "--format=%s"]).splitlines()
    assert any("containerized environment 'tool'" in line for line in log)  # a recorded step

    col.add("tool", "2.0")  # the collection gains a newer image
    fresh = containers_list(dataset=ds, result_renderer="disabled")
    assert fresh == listed
    assert head(Path(ds.path) / "code/containers") == first
    assert (Path(ds.path) / "code/containers/images/tool--2.0.sif").exists() is False


def test_declared_call_format_replaces_the_collections_and_leaves_it_unchanged(tmp_path, ds):
    col = Collection(tmp_path / "col", call_fmt="sh {img} {cmd}")
    rev = col.add("tool", "1.0")
    declare(
        ds,
        [entry(col, rev=rev)],
        [{"name": "tool", "collection": "lab", "version": "1.0", "call_fmt": "sh study.sh {cmd}"}],
    )
    containers.register(ds)
    listed = containers_list(dataset=ds, result_renderer="disabled")
    assert listed[0]["cmdexec"] == "sh study.sh {cmd}"
    sub = Dataset(Path(ds.path) / "code/containers")
    assert head(sub.path) == rev
    assert not sub.repo.call_git(["status", "--porcelain"]).strip()


# -- 3.8 absent version -------------------------------------------------------------------------


def test_missing_image_version_fails_naming_container_and_collection(tmp_path, ds):
    col = Collection(tmp_path / "col")
    col.add("tool", "1.0")
    declare(ds, [entry(col)], [{"name": "tool", "collection": "lab", "version": "9.9"}])
    with pytest.raises(containers.ContainerError) as raised:
        containers.register(ds)
    message = str(raised.value)
    assert "'tool'" in message and "'lab'" in message and "9.9" in message


def test_version_added_after_the_pinned_revision_is_absent(tmp_path, ds):
    col = Collection(tmp_path / "col")
    first = col.add("tool", "1.0")
    col.add("tool", "2.0")
    declare(
        ds,
        [entry(col, rev=first)],
        [{"name": "tool", "collection": "lab", "version": "2.0"}],
    )
    with pytest.raises(containers.ContainerError, match="2.0"):
        containers.register(ds)


# -- 3.9 call format override ---------------------------------------------------------------------


def test_override_importing_a_collection_file_reruns_in_a_fresh_clone(tmp_path):
    from datalad.api import containers_run

    col = Collection(tmp_path / "col", call_fmt="sh {img} {cmd}")
    col.add("tool", "1.0")
    col.write("shared/helper.sh", 'label() { echo "shared:$1"; }\n')
    ds = create(str(tmp_path / "ds"), result_renderer="disabled")
    (Path(ds.path) / "code").mkdir()
    # the study's own entry point imports the shared file from the collection subdataset
    (Path(ds.path) / "code/study.sh").write_text(
        '. code/containers/shared/helper.sh\nlabel "$1" > "$2"\n'
    )
    declare(
        ds,
        [entry(col)],
        [
            {
                "name": "tool",
                "collection": "lab",
                "version": "1.0",
                "call_fmt": "sh code/study.sh {cmd}",
            }
        ],
    )
    containers.register(ds)
    containers_run(
        "alpha out.txt",
        container_name="tool",
        dataset=ds,
        inputs=["code/study.sh", "code/containers/shared/helper.sh"],
        outputs=["out.txt"],
        message="run",
        result_renderer="disabled",
    )
    assert (Path(ds.path) / "out.txt").read_text() == "shared:alpha\n"
    record = json.loads(
        ds.repo.call_git(["log", "-1", "--format=%B"])
        .split("=== Do not change lines below ===")[1]
        .split("^^^ Do not change lines above ^^^")[0]
    )
    assert "code/study.sh" in record["inputs"]
    assert "code/containers/shared/helper.sh" in record["inputs"]

    fresh = clone(ds.path, str(tmp_path / "fresh"), result_renderer="disabled")
    fresh.get(".", get_data=False, recursive=True, result_renderer="disabled")
    (Path(fresh.path) / "out.txt").unlink()
    fresh.repo.call_git(["rm", "-q", "--cached", "out.txt"])
    fresh.repo.call_git(["commit", "-q", "-m", "drop the output"])
    rerun(revision="HEAD~1", dataset=fresh, result_renderer="disabled")
    assert (Path(fresh.path) / "out.txt").read_text() == "shared:alpha\n"
