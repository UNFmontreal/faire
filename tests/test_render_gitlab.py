import json

import yaml
from click.testing import CliRunner

from faire.ciplan import Check, CiPlan, Task
from faire.cli import main
from faire.render import gitlab

TAGS = {"a": ["site-a"], "b": ["site-b"]}


def task(i, rule, sample, site="a", branch=None, artifacts=()):
    return Task(
        id=f"{rule}:{sample}",
        rule=rule,
        sample={"subject": sample},
        site=site,
        order=i,
        branch=branch or f"feature/{sample}",
        artifacts=tuple(artifacts),
    )


def jobs_of(plan):
    doc = gitlab.render(plan, TAGS)
    return {k: v for k, v in doc.items() if k != "stages"}


def test_two_samples_two_jobs_on_the_sites_runners():
    plan = CiPlan("std", "dev", (task(0, "process", "01", "a"), task(0, "process", "02", "b")))
    jobs = jobs_of(plan)
    assert len(jobs) == 2
    by_tag = {tuple(j["tags"]): j for j in jobs.values()}
    assert by_tag[("site-a",)]["script"] == ["faire run --task process:01"]
    assert by_tag[("site-b",)]["script"] == ["faire run --task process:02"]
    assert all(j["needs"] == [] for j in jobs.values())  # samples are independent


def test_ordered_tasks_then_checks():
    plan = CiPlan(
        "std",
        "feature/01",
        (task(0, "A", "01", branch="feature/01"), task(1, "B", "01", branch="feature/01")),
        (Check("c1", True), Check("c2", False)),
    )
    jobs = jobs_of(plan)
    a = next(n for n in jobs if n.startswith("task-0-A"))
    b = next(n for n in jobs if n.startswith("task-1-B"))
    assert jobs[a]["needs"] == [] and jobs[b]["needs"] == [a]
    assert jobs[a]["resource_group"] == jobs[b]["resource_group"] == "std/feature/01"
    for name in ("check-c1", "check-c2"):
        assert jobs[name]["needs"] == [b]  # checks start after the last task
    assert jobs["check-c2"]["allow_failure"] is True
    assert "allow_failure" not in jobs["check-c1"]


def test_empty_plan_has_a_job_that_succeeds():
    jobs = jobs_of(CiPlan("std", "dev"))
    assert list(jobs) == ["nothing-to-do"]
    assert "tags" not in jobs["nothing-to-do"]


def test_artifacts_are_kept_even_when_the_job_fails():
    plan = CiPlan("std", "dev", (task(0, "p", "01", artifacts=[".faire/logs/", "qc.html"]),))
    job = next(iter(jobs_of(plan).values()))
    assert job["artifacts"] == {"paths": [".faire/logs/", "qc.html"], "when": "always"}


def test_downstream_trigger_jobs_wait_for_blocking_checks():
    plan = CiPlan(
        "std",
        "dev",
        (task(0, "p", "01"),),
        (Check("c1", True), Check("c2", False)),
        ("study/analysis",),
    )
    jobs = jobs_of(plan)
    trigger = jobs["downstream-study-analysis"]
    assert trigger["trigger"] == {"project": "study/analysis", "branch": "dev"}
    assert trigger["needs"] == ["check-c1"]
    assert "script" not in trigger and trigger["variables"]["FAIRE_UPSTREAM"] == "std"


def test_jobs_only_invoke_faire_with_identifiers():
    plan = CiPlan("std", "dev", (task(0, "p", "01"),), (Check("c1"),))
    for job in jobs_of(plan).values():
        for line in job["script"]:
            assert line.startswith("faire ")


def test_awkward_identifiers_are_quoted_and_job_names_are_valid():
    plan = CiPlan("std", "dev", (task(0, "p", "a b;c"),))
    name, job = next(iter(jobs_of(plan).items()))
    assert job["script"] == ["faire run --task 'p:a b;c'"]
    assert " " not in name and ";" not in name


def test_cli_renders_a_plan_file(tmp_path):
    plan = CiPlan("std", "dev", (task(0, "p", "01"),), (Check("c1"),))
    path = tmp_path / "plan.json"
    path.write_text(plan.to_json())
    result = CliRunner().invoke(
        main,
        ["ci", "render", "--platform", "gitlab", str(path), "--runner-tags", json.dumps(TAGS)],
    )
    assert result.exit_code == 0, result.output
    doc = yaml.safe_load(result.output)
    assert doc["stages"] == ["tasks", "checks", "downstream"]
    assert CiPlan.from_json(plan.to_json()) == plan
