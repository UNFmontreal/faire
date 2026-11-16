"""Typed views over a ma-DMP document.

The document stays the single source of truth: every class wraps the parsed JSON object and
exposes typed accessors, so fields the model does not know about (other extensions, future
standard fields) are preserved on `dump`. Tooling that writes facts back (releases, issue date,
size, access location) mutates the wrapped document through the setters here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

EXT = "faire"
STAGES = ("collection", "review", "accepted", "release", "archival")
DERIVED = "IsDerivedFrom"


@dataclass(frozen=True)
class Template:
    repository: str
    version: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class Instrument:
    name: str
    instrument_id: str | None
    site: str | None
    persistent_id: str | None = None


@dataclass(frozen=True)
class Source:
    """A provenance link of a dataset to another dataset of the plan."""

    dataset_id: str
    role: str  # "triggering" or "resource"

    @property
    def triggering(self) -> bool:
        return self.role == "triggering"


class _View:
    def __init__(self, raw: dict[str, Any]):
        self.raw = raw

    @property
    def ext(self) -> dict[str, Any]:
        return self.raw.get(EXT) or {}

    def ext_for_write(self) -> dict[str, Any]:
        return self.raw.setdefault(EXT, {})


class Host(_View):
    @property
    def title(self) -> str:
        return self.raw.get("title", "")

    @property
    def host_id(self) -> str | None:
        ids = self.raw.get("host_id") or []
        return ids[0]["identifier"] if ids else None

    @property
    def site_dependent(self) -> bool:
        return bool(self.ext.get("site_dependent", False))

    @property
    def long_term(self) -> bool:
        return bool(self.ext.get("long_term", False)) or bool(self.raw.get("certified_with"))

    @property
    def method(self) -> str | None:
        return self.ext.get("method")

    @property
    def parameters(self) -> dict[str, Any]:
        return self.ext.get("parameters") or {}

    @property
    def secrets(self) -> dict[str, str]:
        return self.ext.get("secrets") or {}


class Distribution(_View):
    @property
    def title(self) -> str:
        return self.raw.get("title", "")

    @property
    def stage(self) -> str | None:
        return self.ext.get("stage")

    @property
    def two_way(self) -> bool:
        return bool(self.ext.get("two_way", False))

    @property
    def filter(self) -> str | None:
        """git-annex matching expression, or None when the distribution covers all files."""
        return self.ext.get("filter")

    @property
    def licenses(self) -> list[str]:
        return [lic["license_ref"] for lic in self.raw.get("license") or [] if "license_ref" in lic]

    @property
    def host(self) -> Host | None:
        host = self.raw.get("host")
        return Host(host) if host is not None else None

    def record_delivery(
        self,
        issued: str | None = None,
        byte_size: int | None = None,
        access_url: str | None = None,
    ) -> None:
        """Write back facts established by a fulfilment."""
        facts = {"issued": issued, "byte_size": byte_size, "access_url": access_url}
        for key, value in facts.items():
            if value is not None:
                self.raw[key] = value


class Dataset(_View):
    @property
    def id(self) -> str:
        return self.raw["dataset_id"]["identifier"]

    @property
    def id_type(self) -> str:
        return self.raw["dataset_id"]["type"]

    @property
    def title(self) -> str:
        return self.raw.get("title", "")

    @property
    def template(self) -> Template | None:
        tpl = self.ext.get("template")
        if not tpl:
            return None
        return Template(
            tpl.get("repository", ""), tpl.get("version", ""), tpl.get("parameters") or {}
        )

    @property
    def distributions(self) -> list[Distribution]:
        return [Distribution(d) for d in self.raw.get("distribution") or []]

    def distributions_at(self, stage: str) -> list[Distribution]:
        return [d for d in self.distributions if d.stage == stage]

    @property
    def instruments(self) -> list[Instrument]:
        out = []
        for res in self.raw.get("technical_resource") or []:
            ext = res.get(EXT) or {}
            pid = (res.get("technical_resource_id") or {}).get("identifier")
            out.append(
                Instrument(res.get("name", ""), ext.get("instrument_id"), ext.get("site"), pid)
            )
        return out

    @property
    def is_instrument_source(self) -> bool:
        return bool(self.raw.get("technical_resource"))

    @property
    def derived_from(self) -> list[tuple[str, str]]:
        """(identifier, identifier type) of every IsDerivedFrom link."""
        return [
            (r["identifier"], r.get("type", ""))
            for r in self.raw.get("related_identifier") or []
            if r.get("relation_type") == DERIVED
        ]

    def source_role(self, source_id: str) -> str:
        role = (self.ext.get("sources") or {}).get(source_id, {}).get("role")
        return role or "triggering"

    @property
    def license(self) -> str | None:
        """The release distribution's license when there is one, else the first licensed one."""
        for group in (self.distributions_at("release"), self.distributions):
            for dist in group:
                if dist.licenses:
                    return dist.licenses[0]
        return None

    @property
    def releases(self) -> list[dict[str, Any]]:
        return self.ext.get("releases") or []

    def add_release(self, record: dict[str, Any]) -> None:
        """Append a release record; a record with an existing id replaces it (re-runs)."""
        releases = self.ext_for_write().setdefault("releases", [])
        for i, existing in enumerate(releases):
            if existing.get("id") == record.get("id"):
                releases[i] = record
                return
        releases.append(record)


class Dmp(_View):
    def __init__(self, document: dict[str, Any]):
        super().__init__(document["dmp"])
        self.document = document

    @property
    def title(self) -> str:
        return self.raw.get("title", "")

    @property
    def sample_entities(self) -> list[str]:
        return list(self.ext.get("sample_entities") or [])

    @property
    def hub_host(self) -> str | None:
        return (self.ext.get("hub") or {}).get("host")

    @property
    def coordinator(self) -> str | None:
        return self.ext.get("coordinator")

    @property
    def datasets(self) -> list[Dataset]:
        return [Dataset(d) for d in self.raw.get("dataset") or []]

    def dataset(self, dataset_id: str) -> Dataset:
        for ds in self.datasets:
            if ds.id == dataset_id:
                return ds
        raise KeyError(dataset_id)

    @property
    def id_types(self) -> set[str]:
        """Identifier types used by the plan's own datasets; links of these types are internal."""
        return {ds.id_type for ds in self.datasets}

    def sources_of(self, dataset: Dataset) -> list[Source]:
        """Sources of a dataset that are datasets of the plan, in declaration order."""
        ids = {ds.id for ds in self.datasets}
        types = self.id_types
        return [
            Source(identifier, dataset.source_role(identifier))
            for identifier, typ in dataset.derived_from
            if typ in types and identifier in ids
        ]

    def derived_datasets(self, dataset_id: str) -> list[Dataset]:
        return [
            ds
            for ds in self.datasets
            if any(s.dataset_id == dataset_id for s in self.sources_of(ds))
        ]


def loads(text: str) -> Dmp:
    return Dmp(json.loads(text))


def load(path: str | Path) -> Dmp:
    return loads(Path(path).read_text())


def dumps(dmp: Dmp) -> str:
    return json.dumps(dmp.document, indent=2, ensure_ascii=False) + "\n"


def dump(dmp: Dmp, path: str | Path) -> None:
    Path(path).write_text(dumps(dmp))
