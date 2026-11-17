import copy

import pytest
from datalad.api import Dataset

from faire import planning, rules
from rulefix import RULES, add_samples, make_derived, write_source


@pytest.fixture
def world(tmp_path):
    src = write_source(tmp_path / "src", {"01/a.txt": "one\n", "02/a.txt": "two\n"})
    ds = make_derived(tmp_path, src)
    return src, ds


def plan(ds, **kw):
    return planning.make_plan(
        ds, rules.load(ds.path), dataset_id="derived", branch="dev", default_site="a", **kw
    )


def test_new_samples_each_get_one_task(world):
    _src, ds = world
    p = plan(ds)
    assert [t.id for t in p.tasks] == ["process:subject=01", "process:subject=02"]
    assert p.tasks[0].sample == {"subject": "01"} and p.tasks[0].site == "a"
    assert p.tasks[0].branch == "feature/subject-01"


def test_plan_changes_nothing_and_is_repeatable(world):
    _src, ds = world
    before = ds.repo.get_hexsha()
    first = plan(ds).to_json()
    assert plan(ds).to_json() == first
    assert ds.repo.get_hexsha() == before and not ds.repo.dirty


def record(ds, task, digest, rule="process"):
    ds.repo.call_git(
        [
            "commit",
            "--allow-empty",
            "-m",
            f"run\n\nfaire-task: {task}\nfaire-rule: {rule}\nfaire-inputs: {digest}",
        ]
    )


def current_digests(ds):
    return {d.id: d.digest for d in planning.due_tasks(ds, rules.load(ds.path), default_site="a")}


def test_nothing_to_do_when_records_match(world):
    _src, ds = world
    for task, digest in current_digests(ds).items():
        record(ds, task, digest)
    assert plan(ds).empty


def test_changed_source_makes_only_that_sample_due(world):
    src, ds = world
    for task, digest in current_digests(ds).items():
        record(ds, task, digest)
    add_samples(src, {"02/a.txt": "two changed\n", "03/a.txt": "three\n"})
    p = plan(ds, update=True)
    assert [t.id for t in p.tasks] == ["process:subject=02", "process:subject=03"]


def test_missed_event_is_found_by_planning_later(world):
    src, ds = world
    for task, digest in current_digests(ds).items():
        record(ds, task, digest)
    add_samples(src, {"04/a.txt": "four\n"})  # no pipeline ran for this
    assert [t.id for t in plan(ds, update=True).tasks] == ["process:subject=04"]


def test_resource_update_leaves_the_plan_unchanged(tmp_path):
    src = write_source(tmp_path / "src", {"01/a.txt": "one\n"})
    res = write_source(tmp_path / "res", {"atlas.txt": "atlas\n"})
    ds = make_derived(tmp_path, src)
    ds.clone(source=res.path, path="sourcedata/res", result_renderer="disabled")
    ds.save(message="resource", result_renderer="disabled")
    for task, digest in current_digests(ds).items():
        record(ds, task, digest)
    add_samples(res, {"atlas.txt": "atlas v2\n"})
    Dataset(ds.path + "/sourcedata/res").update(sibling="origin", merge=True)
    assert plan(ds).empty


def test_unknown_container_fails_before_anything(tmp_path):
    src = write_source(tmp_path / "src", {"01/a.txt": "one\n"})
    bad = copy.deepcopy(RULES)
    bad["rules"][0]["container"] = "ghost"
    ds = make_derived(tmp_path, src, rules=bad)
    with pytest.raises(rules.RuleError, match="process.*ghost"):
        plan(ds)


def test_required_input_missing_leaves_sample_out_of_plan(tmp_path):
    src = write_source(tmp_path / "src", {"01/a.txt": "one\n", "02/a.nii": "nii\n"})
    two = copy.deepcopy(RULES)
    two["rules"][0]["inputs"].append(
        {"pattern": "sourcedata/src/{subject}/*.json", "required": True}
    )
    ds = make_derived(tmp_path, src, rules=two)
    assert plan(ds).empty


def test_plan_is_identical_in_ci_and_by_hand(world, monkeypatch):
    _src, ds = world
    by_hand = plan(ds).to_json()
    for name, value in {"CI": "true", "GITLAB_CI": "true", "CI_COMMIT_SHA": "0" * 40}.items():
        monkeypatch.setenv(name, value)
    assert plan(ds).to_json() == by_hand
