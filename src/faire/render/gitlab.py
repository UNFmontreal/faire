"""GitLab renderer: a child pipeline with one job per task and per check.

Jobs only invoke `faire` with an identifier. Order inside a branch uses `needs`, so a task
starts when the previous task of its branch succeeded; checks need every task; jobs of one
branch share a `resource_group`, so two pipelines never work on a branch concurrently.
"""

from __future__ import annotations

import re
import shlex
from typing import Any

import yaml

from faire.ciplan import PROTECTED, CiPlan, Task

IMAGE = "$FAIRE_IMAGE"


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", text).strip("-")


def task_job_name(task: Task) -> str:
    return f"task-{task.order}-{_slug(task.rule)}-{_slug(task.id)}"[:120]


def check_job_name(check_id: str) -> str:
    return f"check-{_slug(check_id)}"


def render(plan: CiPlan, runner_tags: dict[str, list[str]] | None = None) -> dict[str, Any]:
    runner_tags = runner_tags or {}
    jobs: dict[str, Any] = {}
    previous: dict[str, str] = {}  # branch -> job name of its last task so far
    ordered = sorted(plan.tasks, key=lambda t: (t.branch, t.order))
    for task in ordered:
        name = task_job_name(task)
        job: dict[str, Any] = {
            "stage": "tasks",
            "image": IMAGE,
            "script": [f"faire run --task {shlex.quote(task.id)}"],
            "resource_group": f"{plan.dataset}/{task.branch}",
        }
        tags = runner_tags.get(task.site)
        if tags:
            job["tags"] = list(tags)
        needs = [previous[task.branch]] if task.branch in previous else []
        job["needs"] = needs
        if task.artifacts:
            job["artifacts"] = {"paths": list(task.artifacts), "when": "always"}
        jobs[name] = job
        previous[task.branch] = name

    last_tasks = sorted(set(previous.values()))
    check_names = []
    for check in plan.checks:
        name = check_job_name(check.id)
        job = {
            "stage": "checks",
            "image": IMAGE,
            "script": [f"faire test --check {shlex.quote(check.id)}"],
            "needs": list(last_tasks),
        }
        if not check.blocking:
            job["allow_failure"] = True
        jobs[name] = job
        check_names.append(name)

    blocking = [check_job_name(c.id) for c in plan.checks if c.blocking]
    # downstream datasets follow the stream this pipeline is on (`dev` or `pilot`), and are
    # started for each sample the merged pull requests produced, not for the samples that
    # triggered them
    branch = plan.branch if plan.branch in PROTECTED else "dev"
    for target in plan.downstream:
        for n, sample in enumerate(plan.samples or (None,)):
            variables = {"FAIRE_UPSTREAM": plan.dataset, "FAIRE_REVISION": "$CI_COMMIT_SHA"}
            if sample:
                variables["FAIRE_SAMPLE"] = sample
            suffix = f"-{n + 1}" if len(plan.samples) > 1 else ""
            jobs[f"downstream-{_slug(target)}{suffix}"] = {
                "stage": "downstream",
                "trigger": {"project": target, "branch": branch},
                "variables": variables,
                "needs": blocking or list(last_tasks),
            }

    if not jobs:
        jobs["nothing-to-do"] = {
            "stage": "tasks",
            "script": ["echo 'nothing is due on this branch'"],
        }
    return {"stages": ["tasks", "checks", "downstream"], **jobs}


def render_yaml(plan: CiPlan, runner_tags: dict[str, list[str]] | None = None) -> str:
    return yaml.safe_dump(render(plan, runner_tags), sort_keys=False)
