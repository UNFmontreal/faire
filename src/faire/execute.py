"""Running planned tasks: `datalad containers-run` on the right branch, recorded for planning.

A task's commit message carries the facts planning and re-execution need:

    faire-task, faire-rule, faire-rule-version, faire-container, faire-source (one per source
    revision used), faire-inputs.

A run that changes nothing still leaves a (possibly empty) commit with that record, so the task
is not planned again until its inputs change.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from datalad.api import Dataset, containers_run

from faire import containers as containermod
from faire import identity as identitymod
from faire import planning
from faire import rules as rulemod
from faire.rules import Rule, RuleSet

BASE_BRANCH = "dev"
ENV_SECRETS = "FAIRE_SECRETS"


class RunError(RuntimeError):
    pass


class MissingSecret(RunError):
    pass


@dataclass
class Outcome:
    task: str
    status: str  # "ran" | "skipped"
    message: str = ""
    branch: str = ""
    commit: str | None = None
    notes: list[str] = field(default_factory=list)


def check_secrets(env: Mapping[str, str] | None = None) -> None:
    """Fail early, naming the first absent secret; values are never read into messages."""
    env = os.environ if env is None else env
    missing = [n for n in filter(None, (env.get(ENV_SECRETS) or "").split(",")) if n not in env]
    if missing:
        raise MissingSecret(
            "secret(s) not available to this job: "
            + ", ".join(missing)
            + " (define them in the platform's secret store)"
        )


def _branch_exists(repo, name: str) -> bool:
    return bool(repo.call_git(["branch", "--list", name]).strip())


def _remote_branch(repo, name: str) -> bool:
    try:
        return bool(repo.call_git(["ls-remote", "--heads", "origin", name]).strip())
    except Exception:
        return False


def _checkout_feature(ds: Dataset, branch: str, base: str) -> None:
    """Work on the sample's branch: reuse an open one, start over from `base` when it is merged."""
    repo = ds.repo
    if repo.get_active_branch() == branch:
        return
    if not _branch_exists(repo, branch) and _remote_branch(repo, branch):
        repo.call_git(["fetch", "origin", branch])
        repo.call_git(["branch", branch, f"origin/{branch}"])
    if _branch_exists(repo, branch):
        try:
            repo.call_git(["merge-base", "--is-ancestor", branch, base])
            merged = True
        except Exception:
            merged = False
        repo.call_git(["checkout", "-B", branch, base] if merged else ["checkout", branch])
    else:
        repo.call_git(["checkout", "-b", branch, base])


def _source_revisions(ds: Dataset) -> list[str]:
    out = []
    for sub in ds.subdatasets(result_renderer="disabled", return_type="list"):
        rel = Path(sub["path"]).relative_to(ds.path).as_posix()
        if rel.startswith(planning.SOURCEDATA + "/"):
            out.append(f"{rel}={sub.get('gitshasum') or Dataset(sub['path']).repo.get_hexsha()}")
    return sorted(out)


def _sample_files(rule: Rule, sample: dict[str, str], trees: planning.Trees, sources: set[str]):
    """Resolved input patterns that match at least one file, and the required ones that do not."""
    present, unmet = [], []
    for item in rule.inputs:
        resolved = rulemod.resolve(item.pattern, sample)
        files = trees.for_pattern(resolved, sources)
        if any(rulemod.glob_match(resolved, p) for p in files):
            present.append(resolved)
        elif item.required:
            unmet.append(resolved)
    return present, unmet


def run_task(
    ds: Dataset,
    ruleset: RuleSet,
    task: str,
    *,
    update: bool = False,
    base: str = BASE_BRANCH,
    env: Mapping[str, str] | None = None,
) -> Outcome:
    """Run one task: unmet required inputs skip silently, anything else is an error."""
    env = os.environ if env is None else env
    rule_id, sample = planning.parse_task_id(task)
    rule = ruleset.rule(rule_id)
    check_secrets(env)
    if env.get("CI"):
        identitymod.apply(ds, identitymod.from_environment(env))
    from datalad.api import containers_list

    if rule.container not in {
        r["name"] for r in containers_list(dataset=ds, result_renderer="disabled")
    }:
        raise rulemod.RuleError(
            f"rule {rule.id!r} names container {rule.container!r}, which is not registered "
            "in this dataset"
        )
    declared = {c.name: c for c in containermod.load(ds)}
    spec = declared.get(rule.container) or containermod.ContainerSpec(rule.container, "", "unknown")

    repo = ds.repo
    origin = repo.get_active_branch() or base
    source = rule.trigger.source is not None
    branch = planning.branch_of(sample) if source else origin
    trees = planning.Trees(ds, update)
    sources = planning._own_sources(ds)

    if source:
        trigger_files = trees.source(rule.trigger.source)  # type: ignore[arg-type]
    else:
        later = [r.id for r in ruleset.rules][ruleset.order(rule.id) :]
        trigger_files = planning._effective(repo, trees.own(), planning._task_commits(repo, later))
    inputs, unmet = _sample_files(rule, sample, trees, sources)
    key = planning.task_id(rule.id, sample).split(":", 1)[1]
    found = planning.samples_of(rule, trigger_files)
    if unmet or key not in found:
        why = ", ".join(unmet) if unmet else "no trigger file for this sample"
        return Outcome(task, "skipped", f"{task}: skipped, unmet required input: {why}", origin)
    digest = planning.digest_of(found[key][1])

    if source:
        _checkout_feature(ds, branch, base)
        _update_pointers(ds, rule)

    outputs = [rulemod.resolve(o, sample) for o in rule.outputs]
    message = _message(rule, ruleset, spec, sample, digest, _source_revisions(ds))
    before = repo.get_hexsha()
    try:
        containers_run(
            rulemod.resolve(rule.command, sample),
            container_name=rule.container,
            dataset=ds,
            inputs=inputs,
            outputs=outputs,
            message=message,
            result_renderer="disabled",
            on_failure="stop",
        )
    except Exception as exc:
        _keep_failure_log(ds, rule, task, str(exc))
        raise RunError(f"{task}: execution failed: {exc}") from exc
    if repo.get_hexsha() == before:
        repo.call_git(["commit", "--allow-empty", "-m", message])
    return Outcome(task, "ran", f"{task}: done", branch, repo.get_hexsha())


def _keep_failure_log(ds: Dataset, rule: Rule, task: str, text: str) -> None:
    """Leave the error in the rule's first declared artifact directory, for the job to keep."""
    folders = [a for a in rule.artifacts if a.endswith("/")]
    if not folders:
        return
    name = task.replace(":", "_").replace("/", "_").replace("=", "-").replace(",", "_")
    target = Path(ds.path) / folders[0]
    target.mkdir(parents=True, exist_ok=True)
    (target / f"{name}.failed.log").write_text(text + "\n")


def _update_pointers(ds: Dataset, rule: Rule) -> None:
    """Record the revisions of the sources the task used (the triggering source's pointers)."""
    paths = [
        s["path"]
        for s in ds.subdatasets(result_renderer="disabled", return_type="list")
        if Path(s["path"])
        .relative_to(ds.path)
        .as_posix()
        .startswith(f"{planning.SOURCEDATA}/{rule.trigger.source}")
    ]
    if paths:
        ds.save(
            path=paths,
            message=f"Update sourcedata/{rule.trigger.source} for {rule.id}",
            result_renderer="disabled",
        )


def _message(rule, ruleset, spec, sample, digest, revisions) -> str:
    key = ",".join(f"{k}={v}" for k, v in sample.items())
    lines = [
        f"{rule.id}: {key}",
        "",
        f"faire-task: {planning.task_id(rule.id, sample)}",
        f"faire-rule: {rule.id}",
        f"faire-rule-version: {ruleset.version}",
        f"faire-container: {spec.name} {spec.version}",
        *(f"faire-source: {r}" for r in revisions),
        f"faire-inputs: {digest}",
    ]
    return "\n".join(lines)


def run_all(
    ds: Dataset,
    ruleset: RuleSet,
    *,
    default_site: str,
    update: bool = False,
    base: str = BASE_BRANCH,
    env: Mapping[str, str] | None = None,
) -> list[Outcome]:
    """Run everything due on the checked-out branch, in order, as separate jobs would."""
    start = planning.current_branch(ds)
    outcomes: list[Outcome] = []
    tried: set[tuple[str, str]] = set()

    def drain(branch: str) -> None:
        while True:
            due = [
                d
                for d in planning.due_tasks(ds, ruleset, default_site=default_site, content=True)
                if (branch, d.id) not in tried
            ]
            if not due:
                return
            tried.add((branch, due[0].id))
            outcomes.append(run_task(ds, ruleset, due[0].id, update=update, base=base, env=env))

    for item in planning.due_tasks(
        ds, ruleset, default_site=default_site, update=update, content=False
    ):
        if (start, item.id) in tried:
            continue
        tried.add((start, item.id))
        outcome = run_task(ds, ruleset, item.id, update=update, base=base, env=env)
        outcomes.append(outcome)
        if outcome.status == "ran":
            drain(outcome.branch)
        ds.repo.call_git(["checkout", start])
    if start not in planning.PROTECTED:
        drain(start)
    return outcomes
