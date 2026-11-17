import copy
from pathlib import Path

from faire import execute, planning, rules
from rulefix import RULES, make_derived, write_source

TWO_STEPS = copy.deepcopy(RULES)
TWO_STEPS["rules"].append(
    {
        "id": "refine",
        "trigger": {"paths": ["{subject}/processed.txt"]},
        "container": "tool",
        "command": "sh -c 'mkdir -p {subject} && tr a-z A-Z < {inputs} > {outputs}'",
        "inputs": [{"pattern": "{subject}/processed.txt", "required": True}],
        "outputs": ["{subject}/refined.txt"],
    }
)


def build(tmp_path):
    src = write_source(tmp_path / "src", {"01/a.txt": "one\n"})
    return make_derived(tmp_path, src, rules=TWO_STEPS)


def tree(ds, ref):
    return ds.repo.call_git(["ls-tree", "-r", ref]).splitlines()


def test_content_triggered_task_commits_to_the_triggering_branch(tmp_path):
    ds = build(tmp_path)
    execute.run_task(ds, rules.load(ds.path), "process:subject=01", env={})
    due = planning.due_tasks(ds, rules.load(ds.path), default_site="a")
    assert [d.id for d in due] == ["refine:subject=01"]
    head = ds.repo.get_hexsha()
    out = execute.run_task(ds, rules.load(ds.path), "refine:subject=01", env={})
    assert out.branch == "feature/subject-01" == ds.repo.get_active_branch()
    assert (Path(ds.path) / "01/refined.txt").read_text() == "ONE\n"
    assert ds.repo.call_git(["rev-list", f"{head}..HEAD", "--count"]).strip() == "1"
    assert planning.due_tasks(ds, rules.load(ds.path), default_site="a") == []


def test_run_all_matches_separate_jobs(tmp_path):
    (tmp_path / "separate").mkdir()
    separate = build(tmp_path / "separate")
    for task in ("process:subject=01", "refine:subject=01"):
        execute.run_task(separate, rules.load(separate.path), task, env={})

    (tmp_path / "together").mkdir()
    together = build(tmp_path / "together")
    outcomes = execute.run_all(together, rules.load(together.path), default_site="a", env={})
    assert [o.task for o in outcomes] == ["process:subject=01", "refine:subject=01"]
    assert together.repo.get_active_branch() == "dev"
    # same files, same content on the sample branch
    names = lambda ds: sorted(  # noqa: E731
        line.split("\t")[1] for line in tree(ds, "feature/subject-01") if "sourcedata" not in line
    )
    assert names(together) == names(separate)
    assert together.repo.call_git(["show", "feature/subject-01:01/refined.txt"]) == "ONE\n"


def test_run_all_with_nothing_due_does_nothing(tmp_path):
    ds = build(tmp_path)
    execute.run_all(ds, rules.load(ds.path), default_site="a", env={})
    ds.repo.call_git(["checkout", "dev"])
    ds.repo.call_git(["merge", "--no-ff", "-m", "merge", "feature/subject-01"])
    head = ds.repo.get_hexsha()
    assert execute.run_all(ds, rules.load(ds.path), default_site="a", env={}) == []
    assert ds.repo.get_hexsha() == head
