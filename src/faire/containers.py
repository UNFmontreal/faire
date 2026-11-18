"""Containers a dataset template declares: shared collections, frozen into the dataset.

A template declares the collections it uses (a DataLad dataset of datalad-container images:
source, subdataset path, pinned revision) and the containers its rules run (name, collection,
image version, optional call format). Bootstrap installs each collection as a subdataset at its
pinned revision, then *freezes* every declared container: the entry of the collection's own
configuration is copied into the dataset's `.datalad/config`, with the image path rewritten
under the subdataset and pointing at the declared version, and the call format replaced when
the template declares one. `datalad containers-run -n <name>` then works against the frozen
entry whatever the collection gains later.

Which file holds a version is a convention of the collection: the image of version `V` of tool
`T` is the file named `T--V.<extension>` (the layout of the ReproNim containers). The call
format comes from the collection's entry `T`, unless the declaration gives one.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import yaml
from datalad.api import Dataset

DECLARATION = ".faire/containers.yaml"


class ContainerError(ValueError):
    pass


@dataclass(frozen=True)
class CollectionSpec:
    name: str
    source: str
    path: str  # subdataset path in the dataset
    revision: str  # exact commit or tag the subdataset is pinned to


@dataclass(frozen=True)
class ContainerSpec:
    name: str
    collection: str
    version: str
    call_fmt: str | None = None


@dataclass(frozen=True)
class Declaration:
    collections: tuple[CollectionSpec, ...] = ()
    containers: tuple[ContainerSpec, ...] = ()

    def collection(self, name: str) -> CollectionSpec:
        for spec in self.collections:
            if spec.name == name:
                return spec
        raise ContainerError(f"unknown collection {name!r}")


def parse(raw: dict) -> Declaration:
    collections: list[CollectionSpec] = []
    for entry in raw.get("collections") or []:
        name = entry.get("name", "")
        missing = [k for k in ("name", "source", "path", "revision") if not entry.get(k)]
        if missing:
            raise ContainerError(f"collection {name!r}: {', '.join(missing)} required")
        path = PurePosixPath(str(entry["path"]))
        if path.is_absolute() or ".." in path.parts:
            raise ContainerError(f"collection {name!r}: path {entry['path']!r} must stay inside")
        if any(c.name == name for c in collections):
            raise ContainerError(f"collection {name!r} is declared twice")
        if any(c.path == str(path) for c in collections):
            raise ContainerError(f"collection {name!r}: path {path} is already used")
        collections.append(
            CollectionSpec(name, str(entry["source"]), str(path), str(entry["revision"]))
        )
    containers: list[ContainerSpec] = []
    known = {c.name for c in collections}
    for entry in raw.get("containers") or []:
        name = entry.get("name", "")
        missing = [k for k in ("name", "collection", "version") if not entry.get(k)]
        if missing:
            raise ContainerError(f"container {name!r}: {', '.join(missing)} required")
        if entry["collection"] not in known:
            raise ContainerError(
                f"container {name!r}: collection {entry['collection']!r} is not declared"
            )
        if any(c.name == name for c in containers):
            raise ContainerError(f"container {name!r} is declared twice")
        containers.append(
            ContainerSpec(name, entry["collection"], str(entry["version"]), entry.get("call_fmt"))
        )
    return Declaration(tuple(collections), tuple(containers))


def load(dataset: Dataset | str | Path) -> Declaration:
    root = Path(dataset.path if isinstance(dataset, Dataset) else dataset)
    path = root / DECLARATION
    if not path.exists():
        return Declaration()
    return parse(yaml.safe_load(path.read_text()) or {})


# -- looking into a collection ---------------------------------------------------------------


def find_image(collection: Path, tool: str, version: str) -> str | None:
    """Path, relative to the collection, of the file holding `version` of `tool`."""
    found = []
    for directory, subdirs, files in os.walk(collection):
        subdirs[:] = [d for d in subdirs if d != ".git"]
        for name in files:
            if name.startswith(f"{tool}--{version}.") or name == f"{tool}--{version}":
                found.append(Path(directory, name).relative_to(collection).as_posix())
    if len(found) > 1:
        raise ContainerError(f"{tool} {version}: several images match: {', '.join(sorted(found))}")
    return found[0] if found else None


def entry_call_format(collection: Path, tool: str) -> str | None:
    """The call format of the collection's own entry for `tool`, if it has one."""
    config = collection / ".datalad" / "config"
    if not config.exists():
        return None
    out = subprocess.run(
        ["git", "config", "-f", str(config), "--get", f"datalad.containers.{tool}.cmdexec"],
        capture_output=True,
        text=True,
    )
    return out.stdout.rstrip("\n") if out.returncode == 0 and out.stdout.strip() else None


# -- installing and freezing ----------------------------------------------------------------


def install_collection(dataset: Dataset, spec: CollectionSpec) -> bool:
    """Install the collection as a subdataset at its pinned revision; False if already there."""
    root = Path(dataset.path)
    where = root / spec.path
    if (where / ".git").exists():
        return False
    from datalad.api import clone

    try:
        clone(source=spec.source, path=str(where), dataset=dataset, result_renderer="disabled")
        subprocess.run(
            ["git", "checkout", "--quiet", spec.revision],
            cwd=where,
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise ContainerError(
            f"collection {spec.name!r}: cannot install {spec.source!r} at {spec.revision!r}: "
            f"{detail.strip()}"
        ) from exc
    dataset.save(
        path=spec.path,
        message=f"Install container collection {spec.name} at {spec.revision}",
        result_renderer="disabled",
    )
    return True


def freeze(dataset: Dataset, declaration: Declaration, spec: ContainerSpec) -> None:
    """Register `spec` in the dataset's own container configuration, saved as its own step."""
    from datalad.api import containers_add

    collection = declaration.collection(spec.collection)
    where = Path(dataset.path) / collection.path
    image = find_image(where, spec.name, spec.version)
    if image is None:
        raise ContainerError(
            f"container {spec.name!r}: image version {spec.version!r} is not in collection "
            f"{collection.name!r} at revision {collection.revision!r}"
        )
    call_fmt = spec.call_fmt or entry_call_format(where, spec.name)
    if not call_fmt:
        raise ContainerError(
            f"container {spec.name!r}: collection {collection.name!r} has no entry with a call "
            "format for it and the declaration gives none"
        )
    containers_add(
        spec.name,
        dataset=dataset,
        image=f"{collection.path}/{image}",
        call_fmt=call_fmt,
        result_renderer="disabled",
        on_failure="stop",
    )


def register(dataset: Dataset) -> list[str]:
    """Install the declared collections and freeze the declared containers not yet frozen.

    Returns the names of the containers frozen by this call.
    """
    from datalad.api import containers_list

    declaration = load(dataset)
    for collection in declaration.collections:
        install_collection(dataset, collection)
    known = {r["name"] for r in containers_list(dataset=dataset, result_renderer="disabled")}
    added = []
    for spec in declaration.containers:
        if spec.name in known:
            continue
        freeze(dataset, declaration, spec)
        added.append(spec.name)
    listed = {r["name"] for r in containers_list(dataset=dataset, result_renderer="disabled")}
    absent = [c.name for c in declaration.containers if c.name not in listed]
    if absent:
        raise ContainerError(f"containers not registered after the freeze: {', '.join(absent)}")
    return added
