"""Site configuration: where a site's storage is and how jobs reach its runners.

One YAML file per site, `sites/<site>.yaml` in the study superdataset. Non-secret only:
secrets are referred to by name and held by each site's platform.

    site: a
    hosts:                      # keyed by Host.key (host_id, else title)
      "Site storage":
        type: directory         # git-annex special remote type
        parameters: {directory: /data/a/storage}
        secrets: {}             # parameter -> secret name
    runners:
      tags: [site-a]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from faire import secrets
from faire.model import Dmp

SITES_DIR = "sites"


class SiteConfigError(ValueError):
    pass


@dataclass(frozen=True)
class HostMapping:
    type: str
    parameters: dict[str, Any] = field(default_factory=dict)
    secrets: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SiteConfig:
    site: str
    hosts: dict[str, HostMapping]
    runner_tags: tuple[str, ...] = ()

    def mapping(self, host_key: str) -> HostMapping:
        try:
            return self.hosts[host_key]
        except KeyError:
            raise SiteConfigError(
                f"site {self.site!r} does not map the site-dependent host {host_key!r}"
            ) from None


def parse(data: Any, origin: str = "site configuration") -> SiteConfig:
    if not isinstance(data, dict) or not isinstance(data.get("site"), str) or not data["site"]:
        raise SiteConfigError(f"{origin}: a `site` identifier is required")
    hosts: dict[str, HostMapping] = {}
    for key, raw in (data.get("hosts") or {}).items():
        if not isinstance(raw, dict) or not raw.get("type"):
            raise SiteConfigError(f"{origin}: host {key!r} needs a `type`")
        params = raw.get("parameters") or {}
        named = raw.get("secrets") or {}
        for param, value in named.items():
            if not isinstance(value, str) or not secrets.is_secret_name(value):
                raise SiteConfigError(
                    f"{origin}: host {key!r}: secret {param!r} must name a secret, not hold a value"
                )
        for param in params:
            if secrets.looks_like_credential_key(param) and param not in named:
                raise SiteConfigError(
                    f"{origin}: host {key!r}: parameter {param!r} looks like a credential; "
                    "name a secret in `secrets` instead"
                )
        hosts[key] = HostMapping(raw["type"], dict(params), dict(named))
    tags = (data.get("runners") or {}).get("tags") or []
    if not all(isinstance(t, str) for t in tags):
        raise SiteConfigError(f"{origin}: runner tags must be strings")
    return SiteConfig(data["site"], hosts, tuple(tags))


def load(path: str | Path) -> SiteConfig:
    path = Path(path)
    config = parse(yaml.safe_load(path.read_text()), str(path))
    if path.stem != config.site:
        raise SiteConfigError(f"{path}: file name must match site identifier {config.site!r}")
    return config


def load_all(study_root: str | Path) -> dict[str, SiteConfig]:
    directory = Path(study_root) / SITES_DIR
    if not directory.is_dir():
        return {}
    return {c.site: c for c in (load(p) for p in sorted(directory.glob("*.yaml")))}


def site_dependent_hosts(dmp: Dmp) -> list[str]:
    """Keys of the site-dependent hosts used by the plan, in first-use order."""
    seen: list[str] = []
    for dataset in dmp.datasets:
        for dist in dataset.distributions:
            host = dist.host
            if host is not None and host.site_dependent and host.key not in seen:
                seen.append(host.key)
    return seen


def unmapped_hosts(dmp: Dmp, config: SiteConfig) -> list[str]:
    return [key for key in site_dependent_hosts(dmp) if key not in config.hosts]


def check_site(dmp: Dmp, config: SiteConfig) -> None:
    """Fail naming the first host the plan needs that the site does not map."""
    missing = unmapped_hosts(dmp, config)
    if missing:
        raise SiteConfigError(
            f"site {config.site!r} does not map the site-dependent host(s): "
            + ", ".join(repr(m) for m in missing)
        )
