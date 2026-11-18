"""Checks a dataset declares next to its rules, each runnable on its own."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass

from datalad.api import Dataset

from faire import planning, rules
from faire.rules import Check, RuleError, RuleSet


@dataclass(frozen=True)
class Result:
    check: str
    blocking: bool
    ok: bool
    output: str


def applicable(ruleset: RuleSet, branch: str) -> list[Check]:
    """Checks for a pull request branch; the protected branches carry no pull request."""
    return [] if branch in planning.PROTECTED else list(ruleset.checks)


def run_check(ds: Dataset, ruleset: RuleSet, check_id: str) -> Result:
    """Run one check on the state of the checked-out branch, as a shell command in the dataset."""
    found = next((c for c in ruleset.checks if c.id == check_id), None)
    if found is None:
        raise RuleError(f"no check {check_id!r}")
    branch = planning.current_branch(ds)
    sample = planning.sample_of_branch(branch, rules.entity_names(ds.path)) or {}
    env = {
        **os.environ,
        "FAIRE_BRANCH": branch,  # what the check looks at: the branch and the sample it holds
        "FAIRE_SAMPLE": ",".join(f"{k}={v}" for k, v in sample.items()),
    }
    proc = subprocess.run(
        found.command, shell=True, cwd=ds.path, capture_output=True, text=True, check=False, env=env
    )
    return Result(found.id, found.blocking, proc.returncode == 0, proc.stdout + proc.stderr)
