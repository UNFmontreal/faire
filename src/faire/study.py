"""Study superdataset layout."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

STUDY_FILE = ".faire/study.yaml"


@dataclass(frozen=True)
class StudyLayout:
    name: str
    madmp: str
    sites: str
    default: str = "{id}"
    overrides: dict[str, str] = field(default_factory=dict)

    def path_of(self, dataset_id: str) -> str:
        """Path at which a dataset is registered in the study superdataset."""
        return self.overrides.get(dataset_id) or self.default.format(id=dataset_id)


def load(root: str | Path) -> StudyLayout:
    raw = yaml.safe_load((Path(root) / STUDY_FILE).read_text())
    layout = raw.get("layout") or {}
    return StudyLayout(
        raw["study"],
        raw.get("madmp", "madmp.json"),
        raw.get("sites", "sites"),
        layout.get("default", "{id}"),
        dict(layout.get("overrides") or {}),
    )
