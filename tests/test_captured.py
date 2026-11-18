"""Captured output entities: samples found in the files a task writes (D34)."""

import copy

import pytest
from datalad.api import Dataset

from faire import execute, planning, rules
from rulefix import RULES, add_samples, make_derived, write_source

# input lines read "<subject label> <session label> <file name>"; the labels come from the data
CONVERT = "while read s e n; do mkdir -p sub-$s/ses-$e; echo {subject} > sub-$s/ses-$e/$n.txt; done"

CAPTURED = copy.deepcopy(RULES)
CAPTURED["rules"] = [
    {
        "id": "convert",
        "trigger": {"source": "src"},
        "container": "tool",
        "command": f"sh -c '{CONVERT} < sourcedata/src/{{subject}}/{{session}}/a.txt'",
        "inputs": [{"pattern": "sourcedata/src/{subject}/{session}/*.txt", "required": True}],
        "outputs": ["sub-{subject}/ses-{session}/*.txt"],
        "captured": ["subject", "session"],
    }
]


def world(tmp_path, files=None, rules_=None):
    src = write_source(tmp_path / "src", files or {"PAT42/0301/a.txt": "01 01 first\n"})
    return src, make_derived(tmp_path, src, rules=rules_ or CAPTURED)


def run(ds, task):
    return execute.run_task(ds, rules.load(ds.path), task, env={})


def due(ds, update=False):
    due_tasks = planning.due_tasks(ds, rules.load(ds.path), default_site="a", update=update)
    return [t.id for t in due_tasks]


def message(ds, ref="HEAD"):
    return ds.repo.call_git(["log", "-1", "--format=%B", ref])


def files_of(ds, ref="HEAD"):
    return sorted(ds.repo.call_git(["ls-tree", "-r", "--name-only", ref]).split())


# -- 6.15 the rule model -----------------------------------------------------------------------


def test_captured_entities_are_part_of_the_rule():
    rule = rules.parse(CAPTURED).rules[0]
    assert rule.captured == ("subject", "session")
    assert rule.output_entities() == ["subject", "session"]


def test_captured_entity_must_appear_in_the_outputs():
    broken = copy.deepcopy(CAPTURED)
    broken["rules"][0]["captured"] = ["run"]
    with pytest.raises(rules.RuleError, match="'run' does not appear"):
        rules.parse(broken)


def test_inputs_come_from_the_trigger_sample_and_outputs_from_the_files_written(tmp_path):
    _src, ds = world(tmp_path)
    [task] = due(ds)
    out = run(ds, task)
    assert out.status == "ran"
    # the input was found under the trigger's values; the output carries the labels in the data
    assert "sub-01/ses-01/first.txt" in files_of(ds)
    assert "sub-PAT42" not in " ".join(files_of(ds))


# -- 6.16 the run record -----------------------------------------------------------------------


def test_one_input_sample_one_output_sample(tmp_path):
    _src, ds = world(tmp_path)
    out = run(ds, due(ds)[0])
    assert out.output_samples == [{"subject": "01", "session": "01"}]
    body = message(ds)
    assert "faire-trigger-sample: subject=PAT42,session=0301" in body
    assert body.count("faire-output-sample:") == 1
    assert "faire-output-sample: subject=01,session=01" in body
    assert "DATALAD RUNCMD" in body  # the run record is intact, so the task can be rerun


def test_one_input_sample_several_output_samples(tmp_path):
    _src, ds = world(tmp_path, {"PAT42/0301/a.txt": "01 01 one\n01 02 two\n"})
    out = run(ds, due(ds)[0])
    assert out.output_samples == [
        {"subject": "01", "session": "01"},
        {"subject": "01", "session": "02"},
    ]
    body = message(ds)
    assert "faire-output-sample: subject=01,session=01" in body
    assert "faire-output-sample: subject=01,session=02" in body
    assert {"sub-01/ses-01/one.txt", "sub-01/ses-02/two.txt"} <= set(files_of(ds))


def test_a_rule_without_captured_entities_has_the_trigger_sample_as_output_sample(tmp_path):
    src = write_source(tmp_path / "src", {"01/a.txt": "one\n"})
    ds = make_derived(tmp_path, src)
    out = run(ds, due(ds)[0])
    assert out.output_samples == [{"subject": "01"}]
    assert "faire-output-sample: subject=01" in message(ds)


def test_nothing_matching_fails_and_saves_nothing(tmp_path):
    broken = copy.deepcopy(CAPTURED)
    broken["rules"][0]["command"] = "sh -c 'mkdir -p elsewhere && echo x > elsewhere/x.txt'"
    _src, ds = world(tmp_path, rules_=broken)
    [task] = due(ds)
    with pytest.raises(execute.RunError, match="rule 'convert' wrote no file matching"):
        run(ds, task)
    feature = ds.repo.get_active_branch()
    assert feature.startswith("feature/")
    assert ds.repo.call_git(["rev-list", f"dev..{feature}"]).strip() == ""  # nothing was saved
    assert "elsewhere/x.txt" not in files_of(ds)
    ds.repo.call_git(["checkout", "dev"])
    assert due(ds) == [task]  # no record was written, so the task is still due


# -- 6.17 files outside the patterns -----------------------------------------------------------


def test_files_outside_every_output_pattern_are_reported_and_not_saved(tmp_path):
    noisy = copy.deepcopy(CAPTURED)
    noisy["rules"][0]["command"] = (
        f"sh -c '{CONVERT} < sourcedata/src/{{subject}}/{{session}}/a.txt; echo log > scratch.log'"
    )
    _src, ds = world(tmp_path, rules_=noisy)
    out = run(ds, due(ds)[0])
    assert out.notes == ["scratch.log"]
    assert "scratch.log" in out.message and "not saved" in out.message
    assert "scratch.log" not in files_of(ds)
    assert "sub-01/ses-01/first.txt" in files_of(ds)


# -- 6.18 rerun replaces the recorded outputs of the trigger sample ----------------------------


def test_rerun_replaces_only_the_outputs_its_previous_run_recorded(tmp_path):
    src, ds = world(
        tmp_path,
        {"PAT42/0301/a.txt": "01 01 alpha\n", "PAT43/0301/a.txt": "01 01 gamma\n"},
    )
    for task in due(ds):  # two trigger samples converge on one output sample
        run(ds, task)
        ds.repo.call_git(["checkout", "dev"])
        ds.repo.call_git(
            [
                "merge",
                "--no-ff",
                "-q",
                "-m",
                "merge",
                planning.branch_of(planning.parse_task_id(task)[1]),
            ]
        )
    assert {"sub-01/ses-01/alpha.txt", "sub-01/ses-01/gamma.txt"} <= set(files_of(ds))
    gamma = ds.repo.call_git(["rev-parse", "HEAD:sub-01/ses-01/gamma.txt"])

    add_samples(src, {"PAT42/0301/a.txt": "01 01 beta\n"})  # a correction of one sample's data
    again = [t for t in due(ds, update=True) if "PAT42" in t]
    assert len(again) == 1
    out = run(ds, again[0])
    assert out.status == "ran"
    now = set(files_of(ds))
    assert "sub-01/ses-01/beta.txt" in now
    assert "sub-01/ses-01/alpha.txt" not in now  # what the previous run recorded is replaced
    assert "sub-01/ses-01/gamma.txt" in now  # the other sample's file is untouched
    assert ds.repo.call_git(["rev-parse", "HEAD:sub-01/ses-01/gamma.txt"]) == gamma
    assert Dataset(ds.path).is_installed()
