"""State-based planning: which tasks are due, from the dataset and its sources only.

A task is one rule applied to one sample. It is due when the state of the rule's trigger files,
as recorded by the rule's last run for that sample, differs from the current one, or when the
rule never ran for that sample. A run's commit message carries the record:

    faire-task: process:subject=01
    faire-rule: process
    faire-inputs: <digest of the trigger files' (path, blob) pairs>

A rule's current state ignores the changes made by itself and by the rules ordered after it, so
its own results (or later steps' results) never make it due again.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from datalad.api import Dataset

from faire import rules as rulemod
from faire.ciplan import Check, CiPlan, Task
from faire.rules import Rule, RuleSet

SOURCEDATA = "sourcedata"
PROTECTED = ("dev", "pilot", "main")
TRAILER_TASK = "faire-task"
TRAILER_INPUTS = "faire-inputs"


class PlanError(RuntimeError):
    pass


@dataclass(frozen=True)
class Due:
    rule: Rule
    sample: dict[str, str]
    digest: str
    site: str

    @property
    def key(self) -> str:
        return ",".join(f"{k}={v}" for k, v in self.sample.items())

    @property
    def id(self) -> str:
        return f"{self.rule.id}:{self.key}"


def task_id(rule_id: str, sample: dict[str, str]) -> str:
    return f"{rule_id}:" + ",".join(f"{k}={v}" for k, v in sample.items())


def parse_task_id(text: str) -> tuple[str, dict[str, str]]:
    rule_id, _, rest = text.partition(":")
    sample = {}
    for part in filter(None, rest.split(",")):
        name, sep, value = part.partition("=")
        if not sep:
            raise PlanError(f"malformed task identifier {text!r}")
        sample[name] = value
    return rule_id, sample


def branch_of(sample: dict[str, str]) -> str:
    return "feature/" + "_".join(f"{k}-{v}" for k, v in sample.items()) if sample else "feature/all"


def _entries(repo, prefix: str = "") -> dict[str, str]:
    """Blob id of every tracked file at HEAD, keyed by path (with `prefix` prepended)."""
    out = repo.call_git(["ls-tree", "-r", "-z", "--full-tree", "HEAD"])
    entries = {}
    for item in out.split("\0"):
        if not item:
            continue
        meta, _, path = item.partition("\t")
        _mode, kind, sha = meta.split()
        if kind == "blob":
            entries[prefix + path] = sha
    return entries


def _task_commits(repo, ids: list[str]) -> set[str]:
    if not ids:
        return set()
    pattern = "^faire-rule: (" + "|".join(re.escape(i) for i in ids) + ")$"
    try:
        out = repo.call_git(["log", "--format=%H", "-E", f"--grep={pattern}"])
    except Exception:  # no commits yet
        return set()
    return set(out.split())


def _effective(repo, entries: dict[str, str], excluded: set[str]) -> dict[str, str]:
    """Files as they were before the commits of the excluded rules touched them."""
    if not excluded:
        return entries
    out = {}
    for path in entries:
        for commit in repo.call_git(["log", "--format=%H", "--", path]).split():
            if commit in excluded:
                continue
            try:
                out[path] = repo.call_git(["rev-parse", f"{commit}:{path}"]).strip()
            except Exception:
                pass
            break
    return out


class Trees:
    """Tracked files of the dataset and of its sources, read at their current revision."""

    def __init__(self, dataset: Dataset, update: bool = False):
        self.ds = dataset
        self.update = update
        self._own: dict[str, str] | None = None
        self._sources: dict[str, dict[str, str]] = {}

    def own(self) -> dict[str, str]:
        if self._own is None:
            self._own = _entries(self.ds.repo)
        return self._own

    def source(self, source_id: str) -> dict[str, str]:
        """Files of a source dataset (all instances of a stream), keyed by dataset path."""
        if source_id in self._sources:
            return self._sources[source_id]
        base = f"{SOURCEDATA}/{source_id}"
        files: dict[str, str] = {}
        found = False
        for sub in self.ds.subdatasets(result_renderer="disabled", return_type="list"):
            rel = Path(sub["path"]).relative_to(self.ds.path).as_posix()
            if rel != base and not rel.startswith(base + "/"):
                continue
            found = True
            subds = Dataset(sub["path"])
            if not subds.is_installed():
                self.ds.get(rel, get_data=False, result_renderer="disabled")
            if self.update:
                subds.update(sibling="origin", merge=True, result_renderer="disabled")
            files.update(_entries(subds.repo, rel + "/"))
        if not found:
            raise PlanError(f"source {source_id!r} is not registered under {SOURCEDATA}/")
        self._sources[source_id] = files
        return files

    def for_pattern(self, pattern: str, sources: set[str]) -> dict[str, str]:
        for source_id in sources:
            if pattern.startswith(f"{SOURCEDATA}/{source_id}/"):
                return self.source(source_id)
        return self.own()


def _own_sources(ds: Dataset) -> set[str]:
    """Identifiers of the sources registered under sourcedata/ (first level or stream)."""
    ids = set()
    for sub in ds.subdatasets(result_renderer="disabled", return_type="list"):
        rel = Path(sub["path"]).relative_to(ds.path).parts
        if rel[0] == SOURCEDATA and len(rel) > 1:
            ids.add(rel[1])
    return ids


def digest_of(files: dict[str, str]) -> str:
    h = hashlib.sha256()
    for path in sorted(files):
        h.update(f"{path}\0{files[path]}\n".encode())
    return h.hexdigest()


def samples_of(
    rule: Rule, files: dict[str, str]
) -> dict[str, tuple[dict[str, str], dict[str, str]]]:
    """Samples the trigger files define: key -> (entity values, the sample's files)."""
    entities = rule.entities()
    matches = []
    for pattern in rule.trigger_patterns():
        regex = rulemod.matcher(pattern)
        for path, blob in files.items():
            m = regex.match(path)
            if m:
                matches.append((path, blob, m.groupdict()))
    if not entities:
        return {"": ({}, {p: b for p, b, _ in matches})} if matches else {}
    found: dict[str, dict[str, str]] = {}
    for _p, _b, values in matches:
        if all(e in values for e in entities):
            found[",".join(f"{e}={values[e]}" for e in entities)] = {e: values[e] for e in entities}
    result = {}
    for key, values in sorted(found.items()):
        own = {p: b for p, b, v in matches if all(v.get(k, values[k]) == values[k] for k in v)}
        result[key] = (values, own)
    return result


def last_record(repo, task: str) -> str | None:
    """Input digest recorded by the latest run of a task reachable from HEAD."""
    pattern = f"^{TRAILER_TASK}: {re.escape(task)}$"
    try:
        body = repo.call_git(["log", "-1", "--format=%B", "-E", f"--grep={pattern}"])
    except Exception:
        return None
    m = re.search(rf"^{TRAILER_INPUTS}: (\S+)$", body, re.MULTILINE)
    return m.group(1) if m else None


def site_of(
    path_files: dict[str, str], source_id: str | None, instances: dict[str, str], default: str
) -> str:
    """Site of origin: the instance directory the sample's files sit in, else the default."""
    if source_id is None:
        return default
    base = f"{SOURCEDATA}/{source_id}/"
    for path in path_files:
        if path.startswith(base):
            segment = path[len(base) :].split("/", 1)[0]
            if segment in instances:
                return instances[segment]
    return default


def current_branch(dataset: Dataset) -> str:
    return dataset.repo.get_active_branch() or ""


def due_tasks(
    dataset: Dataset,
    ruleset: RuleSet,
    *,
    default_site: str,
    instances: dict[str, dict[str, str]] | None = None,
    update: bool = False,
    content: bool | None = None,
) -> list[Due]:
    """Due tasks of the dataset's checked-out branch, in rule order. Changes nothing.

    Source-triggered tasks are due on the protected branches (their results arrive through a
    feature branch); content-triggered tasks on any other branch (they commit to it). `content`
    overrides the choice made from the branch name.
    """
    from datalad.api import containers_list

    registered = {r["name"] for r in containers_list(dataset=dataset, result_renderer="disabled")}
    rulemod.check_containers(ruleset, registered)
    trees = Trees(dataset, update)
    sources = _own_sources(dataset)
    ids = [r.id for r in ruleset.rules]
    due = []
    if content is None:
        content = current_branch(dataset) not in PROTECTED
    for index, rule in enumerate(ruleset.rules):
        if rule.trigger.content != content:
            continue
        excluded = _task_commits(dataset.repo, ids[index:])
        if rule.trigger.source is not None:
            files = trees.source(rule.trigger.source)
        else:
            files = _effective(dataset.repo, trees.own(), excluded)
        for sample, own in samples_of(rule, files).values():
            digest = digest_of(own)
            task = task_id(rule.id, sample)
            if last_record(dataset.repo, task) == digest:
                continue
            if not _required_present(rule, sample, trees, sources):
                continue
            site = site_of(
                own,
                rule.trigger.source,
                (instances or {}).get(rule.trigger.source or "", {}),
                default_site,
            )
            due.append(Due(rule, sample, digest, site))
    return due


def _required_present(rule: Rule, sample: dict[str, str], trees: Trees, sources: set[str]) -> bool:
    for item in rule.inputs:
        if not item.required:
            continue
        resolved = rulemod.resolve(item.pattern, sample)
        files = trees.for_pattern(resolved, sources)
        if not any(rulemod.glob_match(resolved, p) for p in files):
            return False
    return True


def make_plan(
    dataset: Dataset,
    ruleset: RuleSet,
    *,
    dataset_id: str,
    branch: str,
    default_site: str,
    instances: dict[str, dict[str, str]] | None = None,
    downstream: tuple[str, ...] = (),
    update: bool = False,
) -> CiPlan:
    due = due_tasks(dataset, ruleset, default_site=default_site, instances=instances, update=update)
    tasks, counters = [], {}
    for item in due:
        target = branch_of(item.sample) if item.rule.trigger.source else branch
        order = counters.get(target, 0)
        counters[target] = order + 1
        tasks.append(
            Task(item.id, item.rule.id, item.sample, item.site, order, target, item.rule.artifacts)
        )
    checks = ()
    if branch not in PROTECTED:
        checks = tuple(Check(c.id, c.blocking) for c in ruleset.checks)
    return CiPlan(
        dataset_id, branch, tuple(tasks), checks, downstream if branch in PROTECTED else ()
    )


def instances_from(dmp) -> dict[str, dict[str, str]]:
    """Per stream dataset id: instance directory name (`<site>_<instrument>`) -> site."""
    out: dict[str, dict[str, str]] = {}
    for dataset in dmp.datasets:
        names = {
            f"{i.site}_{i.instrument_id}": i.site
            for i in dataset.instruments
            if i.site and i.instrument_id
        }
        if names:
            out[dataset.id] = names
    return out
