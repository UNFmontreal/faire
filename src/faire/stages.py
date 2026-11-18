"""The lifecycle stage of each sample of a dataset, read from its history.

collection   indexed in a source dataset, present in the sources of a derived dataset, or on a
             feature branch that nobody has proposed yet
review       a pull request for the sample is open
accepted     the run record of the sample is on `dev` (or `pilot`): its pull request was merged
release      the sample is part of a tagged state of `main`
archival     the study has been archived (recorded by the archival step; none here yet)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from datalad.api import Dataset

from faire import planning
from faire import rules as rulemod

STAGES = ("collection", "review", "accepted", "release", "archival")
_TRAILERS = ("faire-sample", "faire-trigger-sample", "faire-output-sample")
_RECORD = re.compile(rf"^({'|'.join(_TRAILERS)}): (.+)$", re.MULTILINE)


@dataclass
class Evidence:
    """What the history says about one sample."""

    indexed: set[str] = field(default_factory=set)  # commits that indexed it (source datasets)
    processed: set[str] = field(default_factory=set)  # commits that ran a rule for it
    branches: set[str] = field(default_factory=set)  # feature branches that hold it


def _ref(repo, *names: str) -> str | None:
    for name in names:
        try:
            repo.call_git(["rev-parse", "--verify", "-q", name])
            return name
        except Exception:
            continue
    return None


def _reachable(repo, ref: str | None) -> set[str]:
    return set(repo.call_git(["rev-list", ref]).split()) if ref else set()


def _evidence(repo) -> dict[str, Evidence]:
    """Samples named by the records in the history of every branch, with where they are."""
    found: dict[str, Evidence] = {}
    log = repo.call_git(["log", "--all", "--format=%H%x1f%B%x1e"])
    for chunk in filter(None, log.split("\x1e")):
        commit, _, body = chunk.strip("\n").partition("\x1f")
        for kind, key in _RECORD.findall(body):
            entry = found.setdefault(key, Evidence())
            (entry.indexed if kind == "faire-sample" else entry.processed).add(commit.strip())
    heads = repo.call_git(
        ["for-each-ref", "--format=%(refname:short)", "refs/heads", "refs/remotes"]
    )
    for name in heads.split():
        short = name.removeprefix("origin/")
        sample = planning.sample_of_branch(short)
        if sample:
            found.setdefault(planning.sample_key(sample), Evidence()).branches.add(short)
    return found


def _released(repo) -> set[str]:
    main = _ref(repo, "main", "origin/main")
    if main is None:
        return set()
    tags = repo.call_git(["tag", "--list", "--merged", main]).split()
    commits: set[str] = set()
    for tag in tags:
        commits |= _reachable(repo, f"{tag}^{{commit}}")
    return commits


def sample_stages(
    ds: Dataset,
    open_branches: set[str] | None = None,
    rule_samples: set[str] | None = None,
) -> dict[str, str]:
    """Stage of every sample of the dataset, by its `entity=value,...` key.

    `open_branches` are the source branches of the open pull requests when the platform could be
    asked; without it a feature branch that holds unmerged work counts as under review.
    `rule_samples` are samples present in the sources but not yet processed.
    """
    repo = ds.repo
    accepted = _reachable(repo, _ref(repo, "dev", "origin/dev")) | _reachable(
        repo, _ref(repo, "pilot", "origin/pilot")
    )
    released = _released(repo)
    stages: dict[str, str] = {}
    for key, evidence in _evidence(repo).items():
        record = evidence.processed or evidence.indexed
        if record & released:
            stages[key] = "release"
        elif evidence.processed & accepted:
            stages[key] = "accepted"
        elif evidence.indexed & accepted:
            stages[key] = "collection"  # indexed: it stays at collection until it is released
        elif evidence.branches or evidence.processed:
            proposed = open_branches is None or bool(evidence.branches & open_branches)
            stages[key] = "review" if proposed else "collection"
        else:
            stages[key] = "collection"
    for key in rule_samples or ():
        stages.setdefault(key, "collection")
    return dict(sorted(stages.items()))


def source_samples(ds: Dataset, update: bool = False) -> set[str]:
    """Samples the dataset's sources hold, for the rules that read them (none if not installed)."""
    try:
        ruleset = rulemod.load(ds.path)
        trees = planning.Trees(ds, update)
        found: set[str] = set()
        for rule in ruleset.rules:
            if rule.trigger.source is not None:
                files = trees.source(rule.trigger.source)
                found |= set(planning.samples_of(rule, files))
        return found
    except Exception:
        return set()
