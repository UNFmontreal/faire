"""Storage remotes of a dataset: the same rules at bootstrap, at indexing and for subdatasets.

A distribution bound to the stages `collection`, `review` or `accepted` becomes a git-annex
special remote whose wanted-content rule is the distribution's filter. Where the content goes is
the site's business (`SiteConfig.mapping`), so the same ma-DMP gives each site its own storage.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from datalad.api import Dataset

from faire import sites
from faire.model import Dataset as DmpDataset

EARLY_STAGES = ("collection", "review", "accepted")
RESTRICTIONS = "distribution-restrictions"


class RemoteError(RuntimeError):
    pass


def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()


@dataclass(frozen=True)
class RemoteSpec:
    name: str
    stage: str
    type: str
    params: dict[str, Any]
    wanted: str

    def for_repository(self, repo_name: str) -> RemoteSpec:
        """The same remote (same rules) for another repository of the dataset: its own folder."""
        params = dict(self.params)
        if self.type == "directory" and "directory" in params:
            params["directory"] = str(Path(params["directory"]).parent / repo_name)
        return RemoteSpec(self.name, self.stage, self.type, params, self.wanted)


def _transport(host: Any, repo_name: str, site: sites.SiteConfig) -> tuple[str, dict[str, Any]]:
    if host.site_dependent:
        mapping = site.mapping(host.key)
        remote_type, params = mapping.type, dict(mapping.parameters)
    elif host.method:
        remote_type, params = host.method, dict(host.parameters)
    else:
        raise RemoteError(f"host {host.title!r} declares no transfer method")
    if remote_type == "directory" and "directory" in params:
        params["directory"] = str(Path(params["directory"]) / repo_name)
    return remote_type, params


ALL_STAGES = ("collection", "review", "accepted", "release", "archival")


def distribution_specs(
    dataset: DmpDataset,
    repo_name: str,
    site: sites.SiteConfig,
    stages: tuple[str, ...] = EARLY_STAGES,
) -> list[tuple[Any, RemoteSpec]]:
    """Each one-way distribution bound to the given stages with the remote that fulfils it."""
    out: list[tuple[Any, RemoteSpec]] = []
    used: set[str] = set()
    for dist in dataset.distributions:
        if dist.stage not in ALL_STAGES or dist.two_way or dist.host is None:
            continue
        name = f"{dist.stage}-{slug(dist.host.key)}"
        n = 1
        while name in used:
            n += 1
            name = f"{dist.stage}-{slug(dist.host.key)}-{n}"
        used.add(name)
        if dist.stage not in stages:
            continue
        remote_type, params = _transport(dist.host, repo_name, site)
        wanted = dist.filter or "anything"
        if not dist.host.site_dependent:  # pilot content never leaves the site that acquired it
            wanted = f"({wanted}) and not metadata={RESTRICTIONS}=pilot"
        out.append((dist, RemoteSpec(name, dist.stage, remote_type, params, wanted)))
    return out


def specs(
    dataset: DmpDataset,
    repo_name: str,
    site: sites.SiteConfig,
    stages: tuple[str, ...] = EARLY_STAGES,
) -> list[RemoteSpec]:
    """The remotes a repository of `dataset` has at this site for the given stages."""
    return [spec for _dist, spec in distribution_specs(dataset, repo_name, site, stages)]


def names(ds: Dataset) -> set[str]:
    return {r.get("name") for r in ds.repo.get_special_remotes().values()}


def current(ds: Dataset, spec: RemoteSpec) -> bool:
    """True when the remote exists with the wanted rule already set."""
    return (
        spec.name in names(ds)
        and is_enabled(ds, spec.name)
        and ds.repo.get_preferred_content("wanted", spec.name) == spec.wanted
    )


def create(ds: Dataset, spec: RemoteSpec) -> None:
    """Create the special remote (if missing, or enable it here when only known from history)
    and set its wanted rule."""
    repo = ds.repo
    if spec.type == "directory":
        try:
            Path(spec.params["directory"]).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RemoteError(f"cannot create the storage of {spec.name!r}: {exc}") from exc
    if spec.name not in names(ds):
        options = [f"type={spec.type}", "encryption=none"]
        options += [f"{k}={v}" for k, v in spec.params.items()]
        repo.init_remote(spec.name, options)
    elif not is_enabled(ds, spec.name):
        enable(ds, spec)
    repo.set_preferred_content("wanted", spec.wanted, remote=spec.name)


def enable(ds: Dataset, spec: RemoteSpec) -> None:
    """Make a remote that exists in the dataset's history usable from this clone.

    A fresh clone knows the remote only by its configuration in the git-annex branch; the site's
    parameters are given here. Recent git-annex asks for a confirmation of such a configuration,
    which is given because the parameters come from the site's own configuration.
    """
    if spec.name not in names(ds):
        raise RemoteError(f"{ds.path}: no special remote {spec.name!r} in its history")
    options = [f"{k}={v}" for k, v in spec.params.items()]
    out = subprocess.run(
        ["git", "annex", "enableremote", spec.name, *options],
        cwd=ds.path,
        capture_output=True,
        text=True,
    )
    if out.returncode != 0:
        raise RemoteError(f"cannot enable remote {spec.name!r}: {out.stderr.strip()}")
    found = re.search(rf"verifyremote {re.escape(spec.name)} --safe (\d+)", out.stdout + out.stderr)
    if found:
        subprocess.run(
            ["git", "annex", "verifyremote", spec.name, "--safe", found.group(1)],
            cwd=ds.path,
            check=True,
            capture_output=True,
        )


ARCHIVES_REMOTE = "datalad-archives"


def enable_archives(ds: Dataset) -> None:
    """Make the remote that serves files stored inside archives usable from this clone."""
    if ARCHIVES_REMOTE in names(ds):
        enable(ds, RemoteSpec(ARCHIVES_REMOTE, "", "external", {}, "anything"))


def is_enabled(ds: Dataset, name: str) -> bool:
    """Whether this clone can use the special remote (it is configured, not only known)."""
    out = subprocess.run(
        ["git", "config", "--get", f"remote.{name}.annex-uuid"],
        cwd=ds.path,
        capture_output=True,
        text=True,
    )
    return out.returncode == 0 and bool(out.stdout.strip())
