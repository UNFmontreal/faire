import copy
import json
from pathlib import Path

import pytest
from datalad.api import Dataset

from faire import execute, planning, rules
from rulefix import RULES, add_samples, enable_directory_remote, make_derived, write_source


@pytest.fixture
def world(tmp_path):
    src = write_source(tmp_path / "src", {"01/a.txt": "one\n", "02/a.txt": "two\n"})
    return src, make_derived(tmp_path, src)


def run(ds, task, **kw):
    return execute.run_task(ds, rules.load(ds.path), task, env=kw.pop("env", {}), **kw)


def log(ds, ref="HEAD"):
    return ds.repo.call_git(["log", "-1", "--format=%B", ref])


def test_source_task_runs_on_the_sample_branch_with_a_run_record(world):
    _src, ds = world
    out = run(ds, "process:subject=01")
    assert out.status == "ran" and out.branch == "feature/subject-01"
    assert ds.repo.get_active_branch() == "feature/subject-01"
    assert (Path(ds.path) / "01/processed.txt").read_text() == "one\n"
    message = log(ds)
    assert "DATALAD RUNCMD" in message and '"cmd"' in message
    for trailer in (
        "faire-task: process:subject=01",
        "faire-rule: process",
        "faire-rule-version:",
        "faire-container: tool test",
        "faire-source: sourcedata/src=",
        "faire-inputs:",
    ):
        assert trailer in message or trailer.split(":")[0] in message


def test_task_is_not_due_after_its_own_run(world):
    _src, ds = world
    run(ds, "process:subject=01")
    ds.repo.call_git(["checkout", "dev"])
    ds.repo.call_git(["merge", "--no-ff", "-m", "merge", "feature/subject-01"])
    ids = [d.id for d in planning.due_tasks(ds, rules.load(ds.path), default_site="a")]
    assert ids == ["process:subject=02"]


def test_content_of_other_samples_is_not_retrieved(tmp_path):
    from datalad.support.gitrepo import GitRepo

    src = write_source(tmp_path / "src", {"01/a.txt": "one\n", "02/a.txt": "two\n"}, annex=True)
    store = tmp_path / "store"
    store.mkdir()
    src.repo.init_remote("store", ["type=directory", f"directory={store}", "encryption=none"])
    hub = tmp_path / "hub.git"
    GitRepo(str(hub), create=True, bare=True)
    src.siblings("add", name="hub", url=str(hub), result_renderer="disabled")
    src.push(to="store", result_renderer="disabled")
    src.push(to="hub", result_renderer="disabled")  # after the copy, so locations are visible

    class FromHub:
        path = str(hub)

    ds = make_derived(tmp_path, FromHub())
    sub = Dataset(Path(ds.path) / "sourcedata/src")
    enable_directory_remote(sub, "store", store)
    root = Path(sub.path)
    assert not (root / "01/a.txt").exists() and not (root / "02/a.txt").exists()
    run(ds, "process:subject=01")
    assert (root / "01/a.txt").exists()
    assert not (root / "02/a.txt").exists()  # another sample's content was not retrieved


def test_only_declared_inputs_are_requested(tmp_path):
    """The run record lists the resolved patterns of this sample only, and resources declared."""
    src = write_source(tmp_path / "src", {"01/a.txt": "one\n", "02/a.txt": "two\n"})
    ds = make_derived(tmp_path, src)
    run(ds, "process:subject=01")
    record = json.loads(log(ds).split("=== Do not change lines below ===")[1].split("^^^")[0])
    assert record["inputs"] == ["sourcedata/src/01/*.txt"]
    assert record["outputs"] == ["01/processed.txt"]
    assert record["extra_inputs"] == [".datalad/environments/tool/image"]


def test_unmet_required_input_is_a_silent_skip(tmp_path):
    src = write_source(tmp_path / "src", {"01/a.txt": "one\n", "02/b.nii": "nii\n"})
    doc = copy.deepcopy(RULES)
    ds = make_derived(tmp_path, src, rules=doc)
    head, branches = ds.repo.get_hexsha(), ds.repo.call_git(["branch", "--list"])
    out = run(ds, "process:subject=02")
    assert out.status == "skipped" and "unmet required input" in out.message
    assert ds.repo.get_hexsha() == head and ds.repo.call_git(["branch", "--list"]) == branches
    assert not ds.repo.dirty


def test_missing_secret_fails_early_naming_it_and_prints_no_value(world):
    _src, ds = world
    head = ds.repo.get_hexsha()
    env = {"FAIRE_SECRETS": "STORE_KEY,OTHER", "OTHER": "super-secret-value"}
    with pytest.raises(execute.MissingSecret) as err:
        run(ds, "process:subject=01", env=env)
    assert "STORE_KEY" in str(err.value) and "super-secret-value" not in str(err.value)
    assert "OTHER" not in str(err.value)
    assert ds.repo.get_hexsha() == head and ds.repo.get_active_branch() == "dev"


def test_rerun_of_a_sample_on_dev_replaces_only_its_outputs(world):
    src, ds = world
    for sample in ("01", "02"):
        run(ds, f"process:subject={sample}")
        ds.repo.call_git(["checkout", "dev"])
        ds.repo.call_git(["merge", "--no-ff", "-m", f"merge {sample}", f"feature/subject-{sample}"])
    two = (Path(ds.path) / "02/processed.txt").read_text()
    add_samples(src, {"01/a.txt": "one, corrected\n"})
    out = run(ds, "process:subject=01", update=True, base="dev")
    assert out.status == "ran" and out.branch == "feature/subject-01"
    assert (Path(ds.path) / "01/processed.txt").read_text() == "one, corrected\n"
    assert (Path(ds.path) / "02/processed.txt").read_text() == two
    changed = ds.repo.call_git(["diff", "--name-only", "dev", "HEAD"]).split()
    assert "02/processed.txt" not in changed and "01/processed.txt" in changed
