"""The heuristic: the study's Python code that tells the indexer what incoming files mean.

A source dataset's template provides `.faire/heuristic.py`. The indexer loads it from the clone
it is indexing into, so the heuristic in force is the one the dataset holds at that revision.
The module defines functions; only `entities` is required, every other one is optional and has a
default:

    entities(files, ctx) -> {entity name: value}      the sample's entity values (required)
    instrument(files, ctx) -> id | {"id": id, "software": version}
                                                      default: the site's only instrument
    pilot(files, ctx, entities) -> bool               default: False
    keep(file, ctx) -> bool                           default: True
    sensitive(file, ctx) -> bool                      default: False
    placement(file, ctx, entities) -> path            default: <entity values>/<file name>, or just
                                                      the file name inside a subdataset
    subdataset(ctx, entities) -> name | None          default: None (stored in the instance)
    setup(dataset, ctx) -> None                       default: none (the parent's configuration);
                                                      called once on each new subdataset, before
                                                      any file is recorded in it

`files` are `IncomingFile`s, `ctx` is a `Context`. The interface is expected to grow with new
modalities, which is why every function but `entities` may be left out.
"""

from __future__ import annotations

import hashlib
import importlib.util
import posixpath
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HEURISTIC_FILE = ".faire/heuristic.py"
OPTIONAL = ("instrument", "pilot", "keep", "sensitive", "placement", "subdataset", "setup")
_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class HeuristicError(RuntimeError):
    pass


class MissingEntity(HeuristicError):
    """The heuristic did not give a value for an entity the ma-DMP declares."""


@dataclass(frozen=True)
class IncomingFile:
    path: Path  # where the received file is
    name: str  # its path relative to the incoming directory, with `/` separators


@dataclass(frozen=True)
class Context:
    stream: str  # the source dataset (instrument stream) being indexed
    site: str
    entity_names: tuple[str, ...]  # the sample entities the ma-DMP declares, in order
    instruments: tuple[str, ...] = ()  # identifiers of the stream's instruments at this site
    instance: str | None = None  # the instance being indexed into, when it is already known


@dataclass(frozen=True)
class PlacedFile:
    file: IncomingFile
    target: str  # path in the instance (or subdataset)
    sensitive: bool = False


@dataclass
class Decision:
    """What the heuristic decided for one incoming sample, defaults filled in."""

    entities: dict[str, str]
    instrument: str | None
    software: str | None
    pilot: bool
    kept: list[PlacedFile]
    dropped: list[IncomingFile]
    subdataset: str | None
    has_setup: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def sensitive(self) -> list[PlacedFile]:
        return [p for p in self.kept if p.sensitive]


class Heuristic:
    def __init__(self, functions: dict[str, Callable[..., Any]], revision: str, path: Path):
        self.functions = functions
        self.revision = revision  # identifies the file's content; recorded in indexing commits
        self.path = path

    def has(self, name: str) -> bool:
        return name in self.functions

    def call(self, name: str, *args: Any) -> Any:
        try:
            return self.functions[name](*args)
        except HeuristicError:
            raise
        except Exception as exc:
            raise HeuristicError(
                f"heuristic function {name!r} failed: {type(exc).__name__}: {exc}"
            ) from exc


def load(root: str | Path) -> Heuristic:
    """Import the heuristic of the dataset at `root`, from that dataset's own files only."""
    path = Path(root) / HEURISTIC_FILE
    if not path.is_file():
        raise HeuristicError(f"{root}: no heuristic at {HEURISTIC_FILE}")
    text = path.read_bytes()
    revision = hashlib.sha1(text).hexdigest()  # noqa: S324 - content id, not security
    spec = importlib.util.spec_from_file_location(f"faire_heuristic_{revision[:12]}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise HeuristicError(f"{HEURISTIC_FILE}: cannot be loaded: {exc}") from exc
    functions = {}
    for name in ("entities", *OPTIONAL):
        found = getattr(module, name, None)
        if found is None:
            continue
        if not callable(found):
            raise HeuristicError(f"{HEURISTIC_FILE}: {name!r} is not a function")
        functions[name] = found
    if "entities" not in functions:
        raise HeuristicError(f"{HEURISTIC_FILE}: the function `entities` is required")
    return Heuristic(functions, revision, path)


def _safe_value(name: str, value: Any) -> str:
    if not isinstance(value, str) or not _SAFE.match(value):
        raise HeuristicError(
            f"entity {name!r}: value {value!r} must be a name of letters, digits, `.`, `_`, `-`"
        )
    return value


def _entities(heuristic: Heuristic, files: list[IncomingFile], ctx: Context) -> dict[str, str]:
    found = heuristic.call("entities", files, ctx)
    if not isinstance(found, dict):
        raise HeuristicError("`entities` must return a mapping of entity name to value")
    for name in ctx.entity_names:
        if found.get(name) in (None, ""):
            raise MissingEntity(f"the heuristic gives no value for the sample entity {name!r}")
    unknown = [name for name in found if name not in ctx.entity_names]
    if unknown:
        raise HeuristicError(f"entity {unknown[0]!r} is not declared in the ma-DMP")
    return {name: _safe_value(name, found[name]) for name in ctx.entity_names}


def _instrument(
    heuristic: Heuristic, files: list[IncomingFile], ctx: Context
) -> tuple[str | None, str | None]:
    if not heuristic.has("instrument"):
        if len(ctx.instruments) == 1:
            return ctx.instruments[0], None
        return None, None
    found = heuristic.call("instrument", files, ctx)
    if isinstance(found, str):
        return found, None
    if isinstance(found, dict) and found.get("id"):
        software = found.get("software")
        return str(found["id"]), None if software is None else str(software)
    raise HeuristicError("`instrument` must return an identifier or {'id': ..., 'software': ...}")


def _target(name: str, placed: Any) -> str:
    if not isinstance(placed, str) or not placed:
        raise HeuristicError(f"`placement` gave {placed!r} for {name}: a path is required")
    clean = posixpath.normpath(placed)
    if posixpath.isabs(clean) or clean.startswith("..") or clean == ".":
        raise HeuristicError(f"`placement` gave {placed!r} for {name}: outside the dataset")
    if clean.split("/")[0] in (".git", ".datalad"):
        raise HeuristicError(f"`placement` gave {placed!r} for {name}: a reserved path")
    return clean


def decide(heuristic: Heuristic, files: list[IncomingFile], ctx: Context) -> Decision:
    """Ask the heuristic about an incoming sample and fill in the defaults."""
    entities = _entities(heuristic, files, ctx)
    instrument, software = _instrument(heuristic, files, ctx)
    pilot = bool(heuristic.call("pilot", files, ctx, entities)) if heuristic.has("pilot") else False
    subdataset = None
    if heuristic.has("subdataset"):
        subdataset = heuristic.call("subdataset", ctx, entities)
    if subdataset is not None:
        subdataset = _target("the subdataset", subdataset)
    kept: list[PlacedFile] = []
    dropped: list[IncomingFile] = []
    targets: dict[str, IncomingFile] = {}
    for file in files:
        if heuristic.has("keep") and not heuristic.call("keep", file, ctx):
            dropped.append(file)
            continue
        if heuristic.has("placement"):
            placed = heuristic.call("placement", file, ctx, entities)
        else:  # inside a subdataset the path already says which sample it is
            placed = file.name if subdataset else "/".join([*entities.values(), file.name])
        target = _target(file.name, placed)
        if target in targets:
            raise HeuristicError(
                f"{file.name} and {targets[target].name} are both placed at {target}"
            )
        targets[target] = file
        sensitive = heuristic.has("sensitive") and bool(heuristic.call("sensitive", file, ctx))
        kept.append(PlacedFile(file, target, sensitive))
    return Decision(
        entities,
        instrument,
        software,
        pilot,
        kept,
        dropped,
        subdataset,
        heuristic.has("setup"),
    )
