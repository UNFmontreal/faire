"""Fulfilling the distributions of a dataset at a lifecycle stage.

`fulfil` is what `faire sync --stage S` does for one-way distributions: every distribution bound
to the stage is fulfilled, the others are left alone. Hosts that git-annex can reach get their
content through git-annex, so that the dataset records where each file is; the remote of a
`release` or `archival` distribution is created the first time the stage is reached. A
distribution that cannot be fulfilled (a missing secret, an unreachable host) is reported by
name and does not stop the others. Two-way distributions are exchanged with the hub by the
federation module.
"""

from __future__ import annotations

import datetime
import json
import os
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from datalad.api import Dataset

from faire import filters, identity, model, remotes, sites, validate
from faire.model import Dataset as DmpDataset
from faire.model import Distribution


class FulfilmentError(RuntimeError):
    pass


@dataclass
class Outcome:
    distribution: str  # the distribution's title
    status: str  # "done" | "failed" | "incomplete" | "skipped"
    message: str = ""
    remote: str | None = None
    transferred: int = 0
    created: bool = False  # the remote was created by this run (first use of the stage)
    missing: list[str] = field(default_factory=list)  # selected files the host does not hold
    size: int = 0  # bytes the host holds of the dataset
    access_url: str | None = None  # where the deposit can be accessed, for deposit-only hosts

    @property
    def ok(self) -> bool:
        return self.status in ("done", "skipped")


def required_secrets(dist: Distribution, site: sites.SiteConfig) -> list[str]:
    host = dist.host
    if host is None:
        return []
    names = set(host.secrets.values())
    if host.site_dependent:
        try:
            names |= set(site.mapping(host.key).secrets.values())
        except sites.SiteConfigError:
            pass
    return sorted(names)


def _annex(ds: Dataset, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "annex", *args], cwd=ds.path, capture_output=True, text=True)


def _size(ds: Dataset, remote: str) -> int:
    held = _annex(ds, "find", f"--in={remote}", "--format=${bytesize}\\n").stdout.split()
    return sum(int(n) for n in held if n.isdigit())


def _uuid(ds: Dataset, remote: str) -> str:
    out = subprocess.run(
        ["git", "config", "--get", f"remote.{remote}.annex-uuid"],
        cwd=ds.path,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


def selected(ds: Dataset, wanted: str, absent_from: str | None = None) -> list[str]:
    """Files of the checked-out tree that `wanted` selects; with `absent_from`, only those
    git-annex does not record as present on that remote (what is left to transfer)."""
    uuid = _uuid(ds, absent_from) if absent_from else None
    shown = _annex(ds, "whereis", "--json").stdout
    chosen: list[str] = []
    for line in filter(None, shown.splitlines()):
        entry = json.loads(line)
        if uuid and uuid in {w.get("uuid") for w in entry.get("whereis", [])}:
            continue
        meta = _annex(ds, "metadata", "--json", "--key", entry.get("key", "")).stdout.strip()
        fields = (json.loads(meta).get("fields") or {}) if meta else {}
        fields = {k: v for k, v in fields.items() if not k.endswith("-lastchanged")}
        if filters.matches(wanted, entry.get("file", ""), fields):
            chosen.append(entry["file"])
    return sorted(chosen)


def missing_on(ds: Dataset, remote: str, wanted: str) -> list[str]:
    return selected(ds, wanted, absent_from=remote)


class Depositor(Protocol):
    """What a host offers beyond git-annex. `mint` hands out the persistent identifier of a
    released version (None when the host has no such system). `deposit`, which only a host
    without git-annex support has, puts files in by the host's own method."""

    id_type: str

    def deposit(self, dist: Distribution, files: list[Path]) -> str:
        """Put the files on the host; return where they can be accessed."""

    def mint(self, dist: Distribution, tag: str) -> str | None:
        """The identifier of release `tag`, once all of its files are deposited."""


#: adapters by host key; real ones are registered by deployments, tests use a fake one
DEPOSITORS: dict[str, Depositor] = {}


def _ensure_remote(ds: Dataset, spec: remotes.RemoteSpec) -> bool:
    """Create the remote on first use, enable it in a clone that only knows it. True if created."""
    if spec.name not in remotes.names(ds):
        remotes.create(ds, spec)
        return True
    if not remotes.is_enabled(ds, spec.name):
        remotes.enable(ds, spec)
    ds.repo.set_preferred_content("wanted", spec.wanted, remote=spec.name)
    return False


def fulfil(
    ds: Dataset,
    dataset: DmpDataset,
    repo_name: str,
    site: sites.SiteConfig,
    stage: str,
    only: list[str] | None = None,
    env: Mapping[str, str] | None = None,
) -> list[Outcome]:
    """Fulfil the one-way distributions of `dataset` bound to `stage` (or only those named)."""
    env = os.environ if env is None else env
    outcomes: list[Outcome] = []
    pairs = remotes.distribution_specs(dataset, repo_name, site, stages=(stage,))
    for dist, spec in pairs:
        if only and not ({dist.title, spec.name} & set(only)):
            continue
        missing_secrets = [n for n in required_secrets(dist, site) if not env.get(n)]
        if missing_secrets:
            outcomes.append(
                Outcome(
                    dist.title,
                    "failed",
                    "secret(s) not available to this job: " + ", ".join(missing_secrets),
                    spec.name,
                )
            )
            continue
        depositor = DEPOSITORS.get(dist.host.key)
        if depositor and hasattr(depositor, "deposit"):  # no git-annex on this host
            files = [f for f in selected(ds, spec.wanted) if (Path(ds.path) / f).exists()]
            try:
                url = depositor.deposit(dist, [Path(ds.path) / f for f in files])
            except Exception as exc:
                outcomes.append(Outcome(dist.title, "failed", f"{exc}"))
                continue
            size = sum((Path(ds.path) / f).stat().st_size for f in files)
            outcomes.append(
                Outcome(dist.title, "done", "", None, len(files), size=size, access_url=url)
            )
            continue
        try:
            created = _ensure_remote(ds, spec)
            result = ds.push(
                to=spec.name, data="auto", result_renderer="disabled", on_failure="ignore"
            )
        except Exception as exc:
            outcomes.append(Outcome(dist.title, "failed", f"{exc}", spec.name))
            continue
        failed = [r for r in result if r.get("status") not in ("ok", "notneeded")]
        if failed:
            outcomes.append(
                Outcome(
                    dist.title, "failed", failed[0].get("message") or "transfer failed", spec.name
                )
            )
            continue
        moved = len([r for r in result if r.get("action") == "copy" and r.get("status") == "ok"])
        missing = missing_on(ds, spec.name, spec.wanted) if stage in ("release", "archival") else []
        outcome = Outcome(
            dist.title,
            "incomplete" if missing else "done",
            f"{len(missing)} selected file(s) not on the host" if missing else "",
            spec.name,
            moved,
            created,
            missing,
            _size(ds, spec.name),
            spec.params.get("directory") or spec.params.get("url"),
        )
        outcomes.append(outcome)
    if "origin" in ds.repo.get_remotes():  # where the files are is known to every clone
        ds.push(to="origin", data="nothing", result_renderer="disabled", on_failure="ignore")
    return outcomes


def complete(
    ds: Dataset,
    dataset: DmpDataset,
    stage: str,
    outcomes: list[Outcome],
    study: Dataset,
    tag: str | None = None,
    who: identity.Identity | None = None,
) -> list[str]:
    """Write what the fulfilment established to the ma-DMP of the study superdataset.

    Nothing is written, and no identifier is obtained, unless every distribution of the stage is
    complete: every file selected for the release is recorded as present on its host. A release
    (`tag` given at stage `release`) gets one record, with the identifiers its hosts minted; a
    record that already holds an identifier of a distribution is not minted again.
    """
    if not outcomes or not all(o.status == "done" for o in outcomes):
        owing = [o.distribution for o in outcomes if o.status != "done"]
        return [f"incomplete: nothing recorded, no identifier obtained ({', '.join(owing)})"]
    revision = ds.repo.get_hexsha()
    today = datetime.date.today().isoformat()
    facts = {o.distribution: o for o in outcomes}

    def apply(dmp: model.Dmp) -> None:
        target = dmp.dataset(dataset.id)
        record = next((r for r in target.releases if r["id"] == tag), None) if tag else None
        identifiers = list(record["identifiers"]) if record else []
        for dist in target.distributions:
            fact = facts.get(dist.title)
            if fact is None:
                continue
            dist.record_delivery(today, fact.size or None, fact.access_url)
            depositor = DEPOSITORS.get(dist.host.key) if dist.host else None
            minted = any(i.get("distribution") == dist.title for i in identifiers)
            if stage == "release" and tag and depositor and not minted:
                if value := depositor.mint(dist, tag):
                    identifiers.append(
                        {"identifier": value, "type": depositor.id_type, "distribution": dist.title}
                    )
        if stage == "release" and tag:
            target.add_release(
                {"id": tag, "date": today, "revision": revision, "identifiers": identifiers}
            )

    write_back(study, apply, f"Record {stage} of {dataset.id}" + (f" {tag}" if tag else ""), who)
    return [f"recorded in the ma-DMP: {', '.join(facts)}"]


def write_back(
    study: Dataset, apply, message: str, who: identity.Identity | None = None, tries: int = 3
) -> None:
    """Commit a change of the ma-DMP as the automation identity, after re-validation.

    It goes to `dev`, or to `main` where the study has no `dev`. The change is made again on the
    latest branch when the push finds it moved (jobs writing back are serialised by the platform,
    this only covers the rare overlap).
    """
    identity.apply(study, who or identity.from_environment())
    path = Path(study.path) / "madmp.json"
    for attempt in range(tries):
        study.repo.call_git(["fetch", "--quiet", "origin"])
        branch = "dev" if "origin/dev" in study.repo.get_remote_branches() else "main"
        study.repo.call_git(["checkout", "--quiet", "-B", branch, f"origin/{branch}"])
        dmp = model.load(path)
        apply(dmp)
        if problems := validate.validate(dmp.document):
            raise FulfilmentError(f"the updated ma-DMP is not valid: {problems[0]}")
        model.dump(dmp, path)
        study.save(message=message, result_renderer="disabled")
        try:
            study.repo.call_git(["push", "--quiet", "origin", branch])
            return
        except Exception:
            if attempt == tries - 1:
                raise
