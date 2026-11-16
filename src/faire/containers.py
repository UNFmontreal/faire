"""Containers a dataset template declares, registered through datalad-container."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml
from datalad.api import Dataset

DECLARATION = ".faire/containers.yaml"


class ContainerError(ValueError):
    pass


@dataclass(frozen=True)
class ContainerSpec:
    name: str
    url: str
    version: str
    call_fmt: str | None = None


def load(dataset: Dataset | str | Path) -> list[ContainerSpec]:
    root = Path(dataset.path if isinstance(dataset, Dataset) else dataset)
    path = root / DECLARATION
    if not path.exists():
        return []
    specs = []
    for raw in (yaml.safe_load(path.read_text()) or {}).get("containers") or []:
        spec = ContainerSpec(
            raw.get("name", ""),
            raw.get("url", ""),
            str(raw.get("version", "")),
            raw.get("call_fmt"),
        )
        check_pinned(spec)
        specs.append(spec)
    return specs


def check_pinned(spec: ContainerSpec) -> None:
    """A container must name its image and an exact version; registry images need a digest."""
    if not spec.name or not spec.url:
        raise ContainerError(f"container {spec.name!r}: `name` and `url` are required")
    if not spec.version:
        raise ContainerError(f"container {spec.name!r}: an exact `version` is required")
    registry = spec.url.startswith(("docker://", "dhub://", "shub://", "oras://"))
    if registry and "@sha256:" not in spec.url:
        raise ContainerError(
            f"container {spec.name!r}: registry image {spec.url!r} must be pinned by digest "
            "(name@sha256:...)"
        )


def register(dataset: Dataset) -> list[str]:
    """Register every declared container that is not yet registered; return the new names."""
    from datalad.api import containers_add, containers_list

    known = {r["name"] for r in containers_list(dataset=dataset, result_renderer="disabled")}
    added = []
    for spec in load(dataset):
        if spec.name in known:
            continue
        containers_add(
            spec.name,
            dataset=dataset,
            url=spec.url,
            call_fmt=spec.call_fmt,
            result_renderer="disabled",
            on_failure="stop",
        )
        added.append(spec.name)
    return added
