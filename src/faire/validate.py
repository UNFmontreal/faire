"""Validation of a ma-DMP against the base standard and the faire profile."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib import resources
from typing import Any

import jsonschema

from faire import filters
from faire.model import Dataset, Dmp

_UNPINNED = {"main", "master", "head", "latest", "dev", "develop", "trunk"}
_SECRET_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_SECRET_KEY = re.compile(r"(token|password|passwd|secret|api[_-]?key|credential)", re.I)


@dataclass(frozen=True)
class Violation:
    location: str  # JSON pointer into the document
    message: str

    def __str__(self) -> str:
        return f"{self.location or '/'}: {self.message}"


def _schema(name: str) -> dict[str, Any]:
    return json.loads((resources.files("faire") / "schema" / name).read_text())


def _pointer(path: Any) -> str:
    return "".join(f"/{p}" for p in path)


def schema_violations(document: Any) -> list[Violation]:
    out: list[Violation] = []
    for name, label in (("maDMP-schema-1.3.json", "base"), ("faire-profile-1.json", "profile")):
        schema = _schema(name)
        validator = jsonschema.validators.validator_for(schema)(schema)
        for err in sorted(validator.iter_errors(document), key=lambda e: list(map(str, e.path))):
            out.append(Violation(_pointer(err.absolute_path), f"[{label}] {err.message}"))
    return out


def _is_url(value: str) -> bool:
    return bool(re.match(r"^https?://\S+$", value))


def semantic_violations(document: Any) -> list[Violation]:
    """Cross-document rules the schemas cannot express. Skips what is structurally broken."""
    try:
        dmp = Dmp(document)
        raw_datasets = list(dmp.raw.get("dataset") or [])
    except (KeyError, TypeError):
        return []
    out: list[Violation] = []
    datasets: list[tuple[int, Dataset]] = [
        (i, Dataset(d))
        for i, d in enumerate(raw_datasets)
        if isinstance(d, dict)
        and isinstance(d.get("dataset_id"), dict)
        and "identifier" in d["dataset_id"]
    ]
    ids: dict[str, int] = {}
    for i, ds in datasets:
        if ds.id in ids:
            out.append(
                Violation(f"/dmp/dataset/{i}/dataset_id", f"duplicate dataset identifier {ds.id!r}")
            )
        ids.setdefault(ds.id, i)
    types = {ds.id_type for _, ds in datasets}

    graph: dict[str, list[str]] = {}
    for i, ds in datasets:
        base = f"/dmp/dataset/{i}"
        name = ds.id
        tpl = ds.template
        if tpl is not None and (not tpl.version or tpl.version.lower() in _UNPINNED):
            out.append(
                Violation(
                    f"{base}/faire/template/version",
                    f"dataset {name!r}: template version {tpl.version!r} is not pinned",
                )
            )

        # provenance
        sources = []
        for identifier, typ in ds.derived_from:
            if typ in types:
                if identifier not in ids:
                    out.append(
                        Violation(
                            f"{base}/related_identifier",
                            f"dataset {name!r}: IsDerivedFrom {identifier!r} matches no dataset in the plan",
                        )
                    )
                else:
                    sources.append(identifier)
        graph[name] = sources
        if sources and not any(ds.source_role(s) == "triggering" for s in sources):
            out.append(
                Violation(
                    f"{base}/faire/sources",
                    f"dataset {name!r}: every source is resource-only, at least one must be triggering",
                )
            )

        # licenses
        dists = ds.distributions
        if not any(d.licenses for d in dists):
            out.append(
                Violation(
                    f"{base}/distribution", f"dataset {name!r}: no distribution declares a license"
                )
            )
        for j, dist in enumerate(dists):
            loc = f"{base}/distribution/{j}"
            for lic in dist.licenses:
                if not _is_url(lic):
                    out.append(
                        Violation(
                            f"{loc}/license",
                            f"dataset {name!r}, distribution {dist.title!r}: license {lic!r} is not a resolvable identifier",
                        )
                    )
            if dist.stage in ("release", "archival") and not dist.licenses:
                out.append(
                    Violation(
                        f"{loc}/license",
                        f"dataset {name!r}, distribution {dist.title!r}: {dist.stage} distribution declares no license",
                    )
                )
            # archival to long-term hosts
            host = dist.host
            if dist.stage == "archival" and (host is None or not host.long_term):
                out.append(
                    Violation(
                        f"{loc}/host",
                        f"dataset {name!r}, distribution {dist.title!r}: archival host {host.title if host else None!r} is not declared long-term",
                    )
                )
            # filters
            if dist.filter is not None:
                try:
                    filters.parse(dist.filter)
                except filters.FilterError as exc:
                    out.append(
                        Violation(
                            f"{loc}/faire/filter",
                            f"dataset {name!r}, distribution {dist.title!r}: filter {dist.filter!r} cannot be parsed ({exc})",
                        )
                    )
            # secrets
            if host is not None:
                for param, secret in host.secrets.items():
                    if not _SECRET_NAME.match(secret):
                        out.append(
                            Violation(
                                f"{loc}/host/faire/secrets/{param}",
                                f"dataset {name!r}, host {host.title!r}: secret {param!r} holds a value instead of a secret name",
                            )
                        )
                for key in host.parameters:
                    if _SECRET_KEY.search(key) and key not in host.secrets:
                        out.append(
                            Violation(
                                f"{loc}/host/faire/parameters/{key}",
                                f"dataset {name!r}, host {host.title!r}: parameter {key!r} looks like a credential, name a secret in `secrets` instead",
                            )
                        )
            # two-way only to the hub
            if dist.two_way:
                hub = dmp.hub_host
                if hub is None or host is None or host.host_id != hub:
                    out.append(
                        Violation(
                            f"{loc}/faire/two_way",
                            f"dataset {name!r}, distribution {dist.title!r}: two-way distribution must target the declared hub",
                        )
                    )

    # instruments
    seen_site: dict[str, tuple[str, str]] = {}
    for i, ds in datasets:
        base = f"/dmp/dataset/{i}"
        raw_res = ds.raw.get("technical_resource") or []
        local: set[str] = set()
        for k, res in enumerate(raw_res):
            ext = (res or {}).get("faire") or {}
            label = (res or {}).get("name", f"#{k}")
            iid, site = ext.get("instrument_id"), ext.get("site")
            loc = f"{base}/technical_resource/{k}"
            if not iid:
                out.append(
                    Violation(
                        loc,
                        f"dataset {ds.id!r}: instrument {label!r} declares no instrument identifier",
                    )
                )
            if not site:
                out.append(
                    Violation(loc, f"dataset {ds.id!r}: instrument {label!r} declares no site")
                )
            if iid:
                if iid in local:
                    out.append(
                        Violation(
                            loc, f"dataset {ds.id!r}: instrument identifier {iid!r} declared twice"
                        )
                    )
                local.add(iid)
                if site:
                    prior = seen_site.get(iid)
                    if prior and prior[0] != site:
                        out.append(
                            Violation(
                                loc,
                                f"instrument {iid!r} declared at site {prior[0]!r} in dataset {prior[1]!r} and at site {site!r} in dataset {ds.id!r}",
                            )
                        )
                    seen_site.setdefault(iid, (site, ds.id))
        if raw_res:
            if graph.get(ds.id):
                out.append(
                    Violation(
                        base,
                        f"dataset {ds.id!r} declares instruments, so it must be a root dataset",
                    )
                )
            for j, dist in enumerate(ds.distributions):
                host = dist.host
                to_hub = dist.two_way or (
                    host is not None and dmp.hub_host and host.host_id == dmp.hub_host
                )
                if dist.stage == "release" or to_hub:
                    out.append(
                        Violation(
                            f"{base}/distribution/{j}",
                            f"dataset {ds.id!r} declares instruments and cannot have a distribution to the hub or at stage release ({dist.title!r})",
                        )
                    )

    # hub / coordinator
    if dmp.hub_host and not dmp.coordinator:
        out.append(Violation("/dmp/faire/hub", "a hub is declared without a coordinator"))

    # acyclic
    cycle = _find_cycle(graph)
    if cycle:
        out.append(Violation("/dmp/dataset", "provenance cycle: " + " -> ".join(cycle)))
    return out


def _find_cycle(graph: dict[str, list[str]]) -> list[str] | None:
    state: dict[str, int] = {}
    stack: list[str] = []

    def visit(node: str) -> list[str] | None:
        state[node] = 1
        stack.append(node)
        for nxt in graph.get(node, []):
            if state.get(nxt) == 1:
                return stack[stack.index(nxt) :] + [nxt]
            if state.get(nxt) is None:
                found = visit(nxt)
                if found:
                    return found
        stack.pop()
        state[node] = 2
        return None

    for node in graph:
        if state.get(node) is None:
            found = visit(node)
            if found:
                return found
    return None


def validate(document: Any) -> list[Violation]:
    """All violations of the base standard and the profile, in one pass."""
    return schema_violations(document) + semantic_violations(document)
