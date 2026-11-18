"""The neutral task list `faire plan` produces and CI renderers consume.

{"dataset": "standardized", "branch": "dev",
 "tasks": [{"id": "process:subject=01", "rule": "process", "sample": {"subject": "01"},
            "site": "a", "order": 0, "branch": "feature/subject-01",
            "artifacts": [".faire/logs/"]}],
 "checks": [{"id": "layout", "blocking": true}],
 "downstream": ["study/analysis"], "samples": ["subject=01,session=01"]}

`samples` are the output samples of the pull requests merged since the previous pipeline of a
protected branch: the samples the downstream datasets are triggered for.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

PROTECTED = ("dev", "pilot", "main")  # branches that carry no pull request


@dataclass(frozen=True)
class Task:
    id: str
    rule: str
    sample: dict[str, str]
    site: str
    order: int  # position among the tasks that deliver on the same branch
    branch: str  # branch whose state the task builds on
    artifacts: tuple[str, ...] = ()


@dataclass(frozen=True)
class Check:
    id: str
    blocking: bool = True


@dataclass(frozen=True)
class CiPlan:
    dataset: str
    branch: str
    tasks: tuple[Task, ...] = ()
    checks: tuple[Check, ...] = ()
    downstream: tuple[str, ...] = field(default_factory=tuple)
    samples: tuple[str, ...] = field(default_factory=tuple)

    @property
    def empty(self) -> bool:
        return not (self.tasks or self.checks or self.downstream)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2) + "\n"

    @classmethod
    def from_json(cls, text: str) -> CiPlan:
        raw: dict[str, Any] = json.loads(text)
        return cls(
            raw["dataset"],
            raw.get("branch", ""),
            tuple(
                Task(
                    t["id"],
                    t["rule"],
                    dict(t.get("sample") or {}),
                    t["site"],
                    t.get("order", 0),
                    t.get("branch", raw.get("branch", "")),
                    tuple(t.get("artifacts") or ()),
                )
                for t in raw.get("tasks") or []
            ),
            tuple(Check(c["id"], c.get("blocking", True)) for c in raw.get("checks") or []),
            tuple(raw.get("downstream") or ()),
            tuple(raw.get("samples") or ()),
        )
