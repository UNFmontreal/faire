"""Checks a dataset declares next to its rules, each runnable on its own."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

from datalad.api import Dataset

from faire import planning
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
    proc = subprocess.run(
        found.command, shell=True, cwd=ds.path, capture_output=True, text=True, check=False
    )
    return Result(found.id, found.blocking, proc.returncode == 0, proc.stdout + proc.stderr)
