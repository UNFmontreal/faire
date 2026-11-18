"""Running planned tasks: `datalad containers-run` on the right branch, recorded for planning.

A task's commit message carries the facts planning and re-execution need:

    faire-task, faire-rule, faire-rule-version, faire-container, faire-source (one per source
    revision used), faire-inputs, faire-trigger-sample, faire-output-sample (one per sample the
    task wrote files for).

A run that changes nothing still leaves a (possibly empty) commit with that record, so the task
is not planned again until its inputs change.
"""

from __future__ import annotations

import glob
import json
import os
import re
import subprocess
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
    #: the samples the task wrote files for; the trigger sample unless the rule captures entities
    output_samples: list[dict[str, str]] = field(default_factory=list)


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
    declared = {c.name: c for c in containermod.load(ds).containers}
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

    captured = set(rule.captured)
    outputs = [
        rulemod.wildcard(rulemod.resolve(o, sample, keep=captured), captured) for o in rule.outputs
    ]
    message = _message(rule, ruleset, spec, sample, digest, _source_revisions(ds))
    start = repo.get_hexsha()
    prior = _recorded_outputs(repo, task, rule, sample)
    if prior:  # the previous run's outputs are replaced, not added to
        repo.call_git(["rm", "-q", "--", *prior])
        repo.call_git(["commit", "-q", "-m", f"Remove the outputs of the previous {task}"])
    before = repo.get_hexsha()
    try:
        containers_run(
            rulemod.resolve(rule.command, sample),
            container_name=rule.container,
            dataset=ds,
            inputs=inputs,
            outputs=outputs,
            message=message,
            explicit=bool(captured),  # only what the patterns declare is saved
            result_renderer="disabled",
            on_failure="stop",
        )
    except Exception as exc:
        _undo_removal(repo, start, prior)
        _keep_failure_log(ds, rule, task, str(exc))
        raise RunError(f"{task}: execution failed: {exc}") from exc
    written = _changed_files(repo, before)
    notes = _leftovers(repo) if captured else []
    samples = _output_samples(rule, sample, written)
    if captured and not samples:
        _undo_removal(repo, start, prior)
        raise RunError(
            f"{task}: rule {rule.id!r} wrote no file matching its output patterns; nothing saved"
            + (f" (written outside them: {', '.join(notes)})" if notes else "")
        )
    originals = _replaced_originals(repo, before)
    from_pilot = _derives_from_pilot(ds, inputs)
    extra = _sample_lines(sample, samples) + [
        f"faire-original: {key} {path}" for key, path in originals
    ]
    if repo.get_hexsha() == before:
        repo.call_git(["commit", "--allow-empty", "-m", message + "\n" + "\n".join(extra)])
    else:
        repo.call_git(
            ["commit", "--amend", "--allow-empty", "-m", _with_lines(_head_message(repo), extra)]
        )
    _mark_keys(repo, originals, SENSITIVE)  # the identifiable originals stay, marked
    if from_pilot:  # what is made of pilot content is pilot content
        _mark_paths(repo, [p for p in _changed_files(repo, before)], PILOT)
    text = f"{task}: done"
    if notes:
        text += f"; written outside every output pattern, not saved: {', '.join(notes)}"
    return Outcome(task, "ran", text, branch, repo.get_hexsha(), notes, samples)


SENSITIVE, PILOT = "sensitive", "pilot"
RESTRICTIONS = "distribution-restrictions"
_KEY = re.compile(r"[A-Z0-9]+-s\d+(?:-m\d+)?--[0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*")


def _annex(repo, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "annex", *args], cwd=repo.path, capture_output=True, text=True)


def _replaced_originals(repo, before: str) -> list[tuple[str, str]]:
    """(key, path) of the files a run replaced in place: their previous content."""
    if repo.get_hexsha() == before:
        return []
    out = repo.call_git(["diff", "--raw", "-z", "--no-abbrev", "--diff-filter=M", before, "HEAD"])
    fields = out.split("\0")
    keys: list[tuple[str, str]] = []
    for meta, path in zip(fields[0::2], fields[1::2], strict=False):
        parts = meta.lstrip(":").split()
        if len(parts) < 5:
            continue
        old_mode, new_mode, old_sha = parts[0], parts[1], parts[2]
        if "120000" not in (old_mode, new_mode) and old_mode != "100644":
            continue
        found = _KEY.search(repo.call_git(["cat-file", "-p", old_sha]))
        if found and all(found.group(0) != k for k, _ in keys):
            keys.append((found.group(0), path))
    return keys


def _mark_keys(repo, originals: list[tuple[str, str]], value: str) -> None:
    for key, _path in originals:
        _annex(repo, "metadata", "--key", key, "--set", f"{RESTRICTIONS}+={value}")


def _mark_paths(repo, paths: list[str], value: str) -> None:
    annexed = [p for p in paths if repo.is_under_annex(p)]
    if annexed:
        _annex(repo, "metadata", "--set", f"{RESTRICTIONS}+={value}", "--", *annexed)


def _derives_from_pilot(ds: Dataset, inputs: list[str]) -> bool:
    """Whether any input file carries the pilot mark: results of pilot content are pilot too."""
    for pattern in inputs:
        for path in glob.glob(str(Path(ds.path) / pattern), recursive=True):
            folder = str(Path(path).parent)
            top = subprocess.run(
                ["git", "-C", folder, "rev-parse", "--show-toplevel"],
                capture_output=True,
                text=True,
            ).stdout.strip()
            if not top:
                continue
            shown = subprocess.run(
                ["git", "annex", "metadata", "--json", "--", str(Path(path).name)],
                cwd=folder,
                capture_output=True,
                text=True,
            ).stdout
            for line in filter(None, shown.splitlines()):
                marks = (json.loads(line).get("fields") or {}).get(RESTRICTIONS) or []
                if PILOT in marks:
                    return True
    return False


def _undo_removal(repo, start: str, names: list[str]) -> None:
    """Put back the previous outputs removed before a run that did not complete."""
    if names:
        repo.call_git(["reset", "-q", start])
        repo.call_git(["checkout", "--", *names])


def _head_message(repo) -> str:
    return repo.call_git(["log", "-1", "--format=%B"]).rstrip("\n")


MARKER = "\n\n=== Do not change lines below ==="


def _with_lines(message: str, lines: list[str]) -> str:
    """Add trailer lines to the message of a run commit, ahead of datalad's own record."""
    head, marker, tail = message.partition(MARKER)
    return head.rstrip("\n") + "\n" + "\n".join(lines) + marker + tail


def _changed_files(repo, before: str) -> list[str]:
    if repo.get_hexsha() == before:
        return []
    out = repo.call_git(["diff", "--name-only", "--diff-filter=AMT", before, "HEAD"])
    return [line for line in out.splitlines() if line]


def _leftovers(repo) -> list[str]:
    """Files the task left in the working tree that no commit holds (outside every pattern)."""
    out = repo.call_git(["status", "--porcelain", "-uall", "--ignore-submodules=all"])
    return sorted(line[3:].strip('"') for line in out.splitlines() if line)


def _output_samples(rule: Rule, sample: dict[str, str], files: list[str]) -> list[dict[str, str]]:
    """The samples the written files belong to: captured values come from the file paths."""
    entities = rule.output_entities() or list(sample)
    if not rule.captured:
        return [{e: sample[e] for e in entities if e in sample}]
    captured = set(rule.captured)
    patterns = [rulemod.matcher(rulemod.resolve(o, sample, keep=captured)) for o in rule.outputs]
    found: dict[tuple, dict[str, str]] = {}
    for name in files:
        for pattern in patterns:
            hit = pattern.match(name)
            if hit:
                values = {e: hit.group(e) if e in captured else sample[e] for e in entities}
                found[tuple(values.items())] = values
                break
    return [found[k] for k in sorted(found)]


def _key(sample: dict[str, str]) -> str:
    return ",".join(f"{k}={v}" for k, v in sample.items())


def _sample_lines(sample: dict[str, str], outputs: list[dict[str, str]]) -> list[str]:
    return [
        f"faire-trigger-sample: {_key(sample)}",
        *(f"faire-output-sample: {_key(o)}" for o in outputs),
    ]


def _recorded_outputs(repo, task: str, rule: Rule, sample: dict[str, str]) -> list[str]:
    """Files of this rule's output patterns that the task's previous run recorded and that exist."""
    commit = repo.call_git(
        [
            "log",
            "-1",
            "--format=%H",
            "--extended-regexp",
            f"--grep=^faire-task: {re.escape(task)}$",
        ]
    ).strip()
    if not commit or not rule.outputs:
        return []
    captured = set(rule.captured)
    patterns = [rulemod.matcher(rulemod.resolve(o, sample, keep=captured)) for o in rule.outputs]
    names = repo.call_git(["diff-tree", "--no-commit-id", "--name-only", "-r", "--root", commit])
    root = Path(repo.path)
    return [
        n
        for n in names.splitlines()
        if (root / n).exists() or (root / n).is_symlink()
        if any(p.match(n) for p in patterns)
    ]


def _keep_failure_log(ds: Dataset, rule: Rule, task: str, text: str) -> None:
    """Leave the error in the rule's first declared artifact directory, for the job to keep."""
    folders = [a for a in rule.artifacts if a.endswith("/")]
    if not folders:
        return
    name = task.replace(":", "_").replace("/", "_").replace("=", "-").replace(",", "_")
    target = Path(ds.path) / folders[0]
    target.mkdir(parents=True, exist_ok=True)
    (target / f"{name}.failed.log").write_text(text + "\n")


def _sources_of(rule: Rule) -> list[str]:
    """Identifiers of the sources the rule reads: its trigger and every input pattern's source."""
    found = [rule.trigger.source] if rule.trigger.source else []
    prefix = f"{planning.SOURCEDATA}/"
    for item in rule.inputs:
        if item.pattern.startswith(prefix):
            name = item.pattern.removeprefix(prefix).split("/", 1)[0]
            if name and "{" not in name and name not in found:
                found.append(name)
    return found


def _update_pointers(ds: Dataset, rule: Rule) -> None:
    """Record the revisions of the sources the task used, so that the branch (and the pull
    request of it) shows what each source was when the task ran."""
    ids = _sources_of(rule)
    paths = [
        s["path"]
        for s in ds.subdatasets(result_renderer="disabled", return_type="list")
        if any(
            Path(s["path"]).relative_to(ds.path).as_posix() == f"{planning.SOURCEDATA}/{i}"
            or Path(s["path"])
            .relative_to(ds.path)
            .as_posix()
            .startswith(f"{planning.SOURCEDATA}/{i}/")
            for i in ids
        )
    ]
    if paths:
        ds.save(
            path=paths,
            message=f"Update {', '.join(f'sourcedata/{i}' for i in ids)} for {rule.id}",
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
