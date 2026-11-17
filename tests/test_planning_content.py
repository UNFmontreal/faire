import copy
from pathlib import Path

import pytest

from faire import planning, rules
from rulefix import RULES, make_derived, write_source


def content_rules(*ids):
    """Content-triggered rules, in order, all reading {subject}/anat.txt."""
    doc = copy.deepcopy(RULES)
    doc["rules"] = [
        {
            "id": rule_id,
            "trigger": {"paths": ["{subject}/anat.txt"]},
            "container": "tool",
            "command": "true",
            "inputs": [{"pattern": "{subject}/anat.txt", "required": True}],
            "outputs": [f"{{subject}}/{rule_id}.txt"],
        }
        for rule_id in ids
    ]
    return doc


@pytest.fixture
def ds(tmp_path):
    src = write_source(tmp_path / "src", {"01/a.txt": "one\n"})
    ds = make_derived(tmp_path, src, rules=content_rules("A", "B"))
    ds.repo.call_git(["checkout", "-b", "feature/subject-01"])
    return ds


def commit(ds, files, message):
    for name, text in files.items():
        path = Path(ds.path) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    ds.save(message=message, result_renderer="disabled")


def due(ds):
    return planning.due_tasks(ds, rules.load(ds.path), default_site="a")


def as_rule(ds, rule_id, files):
    """Commit changes the way a run of `rule_id` does, recording the digest it saw."""
    seen = {d.rule.id: d for d in due(ds)}
    commit(
        ds,
        files,
        f"run\n\nfaire-task: {rule_id}:subject=01\nfaire-rule: {rule_id}\n"
        f"faire-inputs: {seen[rule_id].digest}",
    )


def test_rules_due_in_their_declared_order(ds):
    commit(ds, {"01/anat.txt": "raw\n"}, "new data")
    plan = planning.make_plan(
        ds, rules.load(ds.path), dataset_id="d", branch="feature/subject-01", default_site="a"
    )
    assert [(t.rule, t.order) for t in plan.tasks] == [("A", 0), ("B", 1)]
    assert {t.branch for t in plan.tasks} == {"feature/subject-01"}


def test_optional_step_drops_out_and_later_rule_still_planned(tmp_path):
    src = write_source(tmp_path / "src", {"01/a.txt": "one\n"})
    doc = content_rules("A", "B")
    doc["rules"][0]["trigger"] = {"paths": ["{subject}/special.txt"]}  # A: optional step
    ds = make_derived(tmp_path, src, rules=doc)
    ds.repo.call_git(["checkout", "-b", "feature/subject-01"])
    commit(ds, {"01/anat.txt": "raw\n"}, "new data")
    assert [d.rule.id for d in due(ds)] == ["B"]


def test_rule_modifying_its_own_inputs_is_not_due_again(ds):
    commit(ds, {"01/anat.txt": "raw\n"}, "new data")
    as_rule(ds, "A", {"01/A.txt": "a\n"})
    as_rule(ds, "B", {"01/anat.txt": "B rewrote its own input\n"})
    assert due(ds) == []


def test_later_rule_modifying_earlier_inputs_does_not_retrigger_it(ds):
    commit(ds, {"01/anat.txt": "raw\n"}, "new data")
    as_rule(ds, "A", {"01/A.txt": "a\n"})
    as_rule(ds, "B", {"01/anat.txt": "defaced\n"})
    assert "A" not in {d.rule.id for d in due(ds)}


def test_outside_change_makes_the_rules_due_again(ds):
    commit(ds, {"01/anat.txt": "raw\n"}, "new data")
    as_rule(ds, "A", {"01/A.txt": "a\n"})
    as_rule(ds, "B", {"01/B.txt": "b\n"})
    assert due(ds) == []
    commit(ds, {"01/anat.txt": "replaced by a person\n"}, "fix")
    assert [d.rule.id for d in due(ds)] == ["A", "B"]
