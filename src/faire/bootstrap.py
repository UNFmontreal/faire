"""Bootstrap: realise a ma-DMP as DataLad datasets, local-only mode.

The workspace plays the part of the platform: repositories live under `<root>/repos/` and every
dependent dataset installs its sources from there. A platform adapter replaces `Workspace.url`
and repository creation later; the steps are the same.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from datalad.api import Dataset, clone, create

from faire import containers, plan, sites, study, templates
from faire.model import Dmp
from faire.plan import Item
from faire.platform import Platform, Repository

RECORD = ".faire/dataset.yaml"
BRANCHES = ("dev", "pilot", "main")
EARLY_STAGES = ("collection", "review", "accepted")
MAIN = "main"
PROTECTED_BRANCHES = ("dev", "pilot", "main")
SAMPLE_BRANCHES = "feature/*"  # branches the tool opens for samples; may read task secrets
REQUIRED_OPERATIONS = (
    "ensure_group",
    "ensure_repository",
    "protect_branch",
    "protect_tag",
    "set_variable",
)
STUDY_REPO = "study"


class BootstrapError(RuntimeError):
    pass


@dataclass
class Workspace:
    root: Path

    def __post_init__(self) -> None:
        self.root = Path(self.root).resolve()

    @property
    def repos(self) -> Path:
        return self.root / "repos"

    @property
    def study(self) -> Path:
        return self.root / "study"

    def repo_path(self, item: Item) -> Path:
        return self.repos / item.repo_name

    def url(self, item: Item) -> str:
        return str(self.repo_path(item))


@dataclass
class Result:
    actions: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    differences: list[str] = field(default_factory=list)  # non-additive, reported not applied
    notes: list[str] = field(default_factory=list)
    #: secret name -> repositories that need it and cannot see it yet
    missing_secrets: dict[str, list[str]] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.actions)


def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()


def spdx_id(license_url: str | None) -> str:
    """SPDX identifier when the license reference is an spdx.org address, else empty."""
    if license_url and re.match(r"^https?://spdx\.org/licenses/", license_url):
        return license_url.rstrip("/").rsplit("/", 1)[1].removesuffix(".html")
    return ""


def record_for(dmp: Dmp, item: Item) -> dict[str, Any]:
    """What the dataset records about the ma-DMP entry it realises (D8)."""
    dataset = dmp.dataset(item.dataset_id)
    tpl = dataset.template
    record: dict[str, Any] = {
        "dataset_id": item.dataset_id,
        "template": {
            "repository": tpl.repository,
            "version": tpl.version,
            "parameters": tpl.parameters,
        },
        "sources": [{"path": s.path, "key": s.key, "role": s.role} for s in item.sources],
        "license": dataset.license,
    }
    if item.is_instance:
        record.update(stream=item.stream, instance=item.instance, site=item.site)
        record["instrument"] = item.instrument
    return record


class Bootstrap:
    def __init__(
        self,
        dmp: Dmp,
        site_config: sites.SiteConfig,
        workspace: Workspace,
        madmp_path: str | Path,
        study_template: str,
        sites_dir: str | Path | None = None,
        dry_run: bool = False,
        platform: Platform | None = None,
        group: str | None = None,
        faire_image: str | None = None,
    ):
        self.platform = platform
        self.group = group or slug(dmp.title) or "study"
        self.faire_image = faire_image
        self.repositories: dict[str, Repository] = {}
        self.dmp = dmp
        self.site = site_config
        self.ws = workspace
        self.madmp_path = Path(madmp_path)
        self.study_template = study_template
        self.sites_dir = Path(sites_dir) if sites_dir else None
        self.dry = dry_run
        self.result = Result()
        self.items = {i.key: i for i in plan.creation_plan(dmp, site_config.site)}
        self._would_exist: set[str] = set()

    # -- helpers -----------------------------------------------------------------------------

    def do(self, message: str, action: Any = None) -> None:
        self.result.actions.append(message)
        if not self.dry and action is not None:
            action()

    def exists(self, item: Item) -> bool:
        return self.ws.repo_path(item).exists() or item.key in self._would_exist

    # -- datasets ----------------------------------------------------------------------------

    def run(self) -> Result:
        if self.platform is None:
            return self._run()
        with self.platform.git_auth():
            return self._run()

    def _run(self) -> Result:
        sites.check_site(self.dmp, self.site)
        if self.platform is not None:
            self.platform.require(REQUIRED_OPERATIONS)  # before any change is made
            if not self.dry:
                self.platform.ensure_group(self.group)
        for item in self.items.values():
            if not item.create:
                self.result.skipped.append(
                    f"{item.key}: instance of site {item.site!r}, referenced not created"
                )
                continue
            if self.ws.repo_path(item).exists():
                if not self.reconcile_existing(item):
                    continue
                self.publish_if_missing(item)
            else:
                self.create_dataset(item)
                self.install_sources(item)
                self.publish_new(item)
            self.configure_remotes(item)
            self.configure_platform(item)
        self.report_unplanned()
        self.create_study()
        self.report_missing_secrets()
        return self.result

    # -- platform ------------------------------------------------------------------------------

    def url(self, item: Item) -> str:
        if self.platform is None:
            return self.ws.url(item)
        repo = self.repositories.get(item.key) or self.platform.get_repository(
            self.group, item.repo_name
        )
        if repo is None:
            raise BootstrapError(f"{item.key}: no repository on the platform yet")
        return repo.url

    def _publish(self, ds: Dataset, name: str, key: str) -> Repository:
        assert self.platform is not None
        repo = self.platform.ensure_repository(self.group, name)
        self.repositories[key] = repo
        if "origin" not in ds.repo.get_remotes():
            ds.siblings("add", name="origin", url=repo.url, result_renderer="disabled")
        # git-annex may write to the remote while the push updates availability information,
        # which makes the first attempt on the git-annex branch a non-fast-forward; the second
        # attempt merges it
        failed = ds.push(
            to="origin", data="nothing", result_renderer="disabled", on_failure="ignore"
        )
        if any(r.get("status") not in ("ok", "notneeded") for r in failed):
            ds.push(to="origin", data="nothing", result_renderer="disabled")
        # the git-annex branch is synchronised by the push above, which merges what the
        # remote holds; pushing it again as a plain branch is rejected once the remote moved
        branches = [
            b for b in ds.repo.get_branches() if b not in (ds.repo.get_active_branch(), "git-annex")
        ]
        if branches:
            ds.repo.push(remote="origin", refspec=branches)
        return repo

    def publish_new(self, item: Item) -> None:
        if self.platform is None:
            return
        self.do(
            f"publish {item.key} as {self.group}/{item.repo_name}",
            lambda: self._publish_and_protect(item),
        )

    def _publish_and_protect(self, item: Item) -> None:
        repo = self._publish(Dataset(self.ws.repo_path(item)), item.repo_name, item.key)
        self.protect(repo)

    def publish_if_missing(self, item: Item) -> None:
        """A dataset created in local-only mode and later bootstrapped with a platform."""
        if self.platform is None or self.platform.get_repository(self.group, item.repo_name):
            return
        self.publish_new(item)

    def protect(self, repo: Repository) -> None:
        """Merge-only branches, approvals, protected release tags, sample branches (D32)."""
        assert self.platform is not None
        for pattern in PROTECTED_BRANCHES:
            result = self.platform.protect_branch(repo, pattern, approvals=1)
            for note in result.notes:
                if note not in self.result.notes:
                    self.result.notes.append(note)
        self.platform.protect_branch(repo, SAMPLE_BRANCHES, approvals=0)
        self.platform.protect_tag(repo, "*")

    def variables_for(self, item: Item) -> dict[str, str]:
        """CI variables derived from the ma-DMP: sources, downstream datasets, secret names."""
        downstream = sorted(
            {
                other.repo_name
                for other in self.items.values()
                if any(link.key == item.key for link in other.sources)
            }
        )
        variables = {
            "FAIRE_DATASET": item.dataset_id,
            "FAIRE_SOURCES": ",".join(sorted({self.items[s.key].repo_name for s in item.sources})),
            "FAIRE_DOWNSTREAM": ",".join(f"{self.group}/{name}" for name in downstream),
            "FAIRE_SECRETS": ",".join(sorted(self.secrets_for(item))),
        }
        if self.faire_image:
            variables["FAIRE_IMAGE"] = self.faire_image
        tags = self.runner_tags()
        if tags:
            variables["FAIRE_RUNNER_TAGS"] = json.dumps(tags, sort_keys=True)
        return variables

    def runner_tags(self) -> dict[str, list[str]]:
        """Runner tags of every site, from the site configurations of the study."""
        configs = {self.site.site: self.site}
        if self.sites_dir and self.sites_dir.is_dir():
            for path in sorted(self.sites_dir.glob("*.yaml")):
                config = sites.load(path)
                configs.setdefault(config.site, config)
        return {site: list(c.runner_tags) for site, c in configs.items() if c.runner_tags}

    def secrets_for(self, item: Item) -> set[str]:
        names: set[str] = set()
        for dist in self.dmp.dataset(item.dataset_id).distributions:
            host = dist.host
            if host is None:
                continue
            names |= set(host.secrets.values())
            if host.site_dependent and host.key in self.site.hosts:
                names |= set(self.site.mapping(host.key).secrets.values())
        return names

    def configure_platform(self, item: Item) -> None:
        if self.platform is None:
            return
        repo = self.repositories.get(item.key) or self.platform.get_repository(
            self.group, item.repo_name
        )
        if repo is None:
            return  # dry run, not published yet
        current = self.platform.get_variables(repo)
        for key, value in self.variables_for(item).items():
            if current.get(key) != value:
                self.do(
                    f"set CI variable {key} on {repo.path}",
                    lambda key=key, value=value, repo=repo: self.platform.set_variable(
                        repo, key, value
                    ),
                )

    def report_missing_secrets(self) -> None:
        if self.platform is None:
            return
        for item in self.items.values():
            repo = self.repositories.get(item.key) or self.platform.get_repository(
                self.group, item.repo_name
            )
            if not item.create or repo is None:
                continue
            defined = self.platform.defined_variables(repo)
            for name in sorted(self.secrets_for(item) - defined):
                self.result.missing_secrets.setdefault(name, []).append(repo.path)

    # -- reconcile existing datasets ---------------------------------------------------------

    def reconcile_existing(self, item: Item) -> bool:
        """Apply additive differences to an existing dataset; report the others.

        Returns False when the dataset differs non-additively and must be left untouched.
        """
        path = self.ws.repo_path(item)
        recorded = yaml.safe_load((path / RECORD).read_text())
        expected = record_for(self.dmp, item)
        problems = []
        if recorded["template"] != expected["template"]:
            problems.append("template, version or parameters changed")
        old = {s["path"]: s for s in recorded["sources"]}
        new = {s["path"]: s for s in expected["sources"]}
        removed = sorted(set(old) - set(new))
        if removed:
            problems.append("sources removed: " + ", ".join(removed))
        added = [p for p in new if p not in old]
        other = [p for p in added if not self.items[new[p]["key"]].is_instance]
        if other:
            problems.append("sources added to an existing dataset: " + ", ".join(other))
        if problems:
            self.result.differences.append(f"{item.key}: " + "; ".join(problems))
            return False
        for subpath in added:
            self.register_instance(item, self.items[new[subpath]["key"]], new[subpath])
        return True

    def register_instance(self, item: Item, source: Item, link: dict[str, Any]) -> None:
        """Propose a new instrument instance as a source of an existing derived dataset.

        The change is made on a branch `register/<instance>` of the derived dataset, to be
        reviewed through a pull request; the dataset's own branches are left untouched.
        """
        branch = f"register/{source.instance}"
        path = self.ws.repo_path(item)
        if branch in Dataset(path).repo.get_branches() or not self.exists(source):
            if not self.exists(source):
                self.result.skipped.append(f"{item.key}: {link['path']} not available here")
            return
        self.do(
            f"propose instance {source.instance} as source of {item.key} on branch {branch}",
            lambda: self._propose(item, source, link, branch),
        )

    def _propose(self, item: Item, source: Item, link: dict[str, Any], branch: str) -> None:
        ds = Dataset(self.ws.repo_path(item))
        repo = ds.repo
        previous = repo.get_active_branch()
        repo.call_git(["branch", branch, "dev"])
        repo.checkout(branch)
        try:
            self._install(Path(ds.path), link["path"], source)
            record = Path(ds.path) / RECORD
            data = yaml.safe_load(record.read_text())
            data["sources"].append(link)
            record.write_text(yaml.safe_dump(data, sort_keys=False))
            ds.save(
                message=f"Register instrument instance {source.instance}",
                result_renderer="disabled",
            )
        finally:
            repo.checkout(previous)

    def report_unplanned(self) -> None:
        if not self.ws.repos.exists():
            return
        planned = {i.repo_name for i in self.items.values()}
        for path in sorted(self.ws.repos.iterdir()):
            if path.is_dir() and path.name not in planned:
                self.result.differences.append(f"{path.name}: exists but is not in the ma-DMP")

    def create_dataset(self, item: Item) -> None:
        path = self.ws.repo_path(item)
        if path.exists():
            return
        self._would_exist.add(item.key)
        self.do(f"create dataset {item.key} from its template", lambda: self._create(item))

    def _create(self, item: Item) -> None:
        path = self.ws.repo_path(item)
        dataset = self.dmp.dataset(item.dataset_id)
        tpl = dataset.template
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            ds = create(str(path), result_renderer="disabled")
            data = {
                **tpl.parameters,
                "dataset_id": item.dataset_id,
                "dataset_title": dataset.title,
                "license": dataset.license or "",
                "license_spdx": spdx_id(dataset.license),
                "derived_from": [s.path for s in item.sources],
            }
            templates.render(tpl.repository, ds, data, tpl.version)
            record = Path(ds.path) / RECORD
            record.parent.mkdir(parents=True, exist_ok=True)
            record.write_text(yaml.safe_dump(record_for(self.dmp, item), sort_keys=False))
            containers.register(ds)
            ds.save(message="Create dataset from its template", result_renderer="disabled")
            self._branches(ds)
        except BaseException:
            shutil.rmtree(path, ignore_errors=True)
            raise

    @staticmethod
    def _branches(ds: Dataset) -> None:
        repo = ds.repo
        if repo.get_active_branch() != MAIN:
            repo.call_git(["branch", "-M", MAIN])
        for branch in BRANCHES:
            if branch not in repo.get_branches():
                repo.call_git(["branch", branch])

    def install_sources(self, item: Item) -> None:
        path = self.ws.repo_path(item)
        for link in item.sources:
            source = self.items[link.key]
            if not source.create or not self.exists(source):
                self.result.skipped.append(
                    f"{item.key}: source {link.path} is not available here, referenced only"
                )
                continue
            if (path / link.path / ".git").exists():
                continue
            self.do(
                f"install source {link.path} in {item.key} ({link.role})",
                lambda p=path, link=link, source=source: self._install(p, link.path, source),
            )

    def _install(self, path: Path, subpath: str, source: Item) -> None:
        ds = Dataset(path)
        clone(
            source=self.url(source),
            path=str(path / subpath),
            dataset=ds,
            result_renderer="disabled",
        )

    # -- storage remotes ---------------------------------------------------------------------

    def configure_remotes(self, item: Item) -> None:
        dataset = self.dmp.dataset(item.dataset_id)
        used: set[str] = set()
        for dist in dataset.distributions:
            if dist.stage not in EARLY_STAGES or dist.two_way or dist.host is None:
                continue
            name = f"{dist.stage}-{slug(dist.host.key)}"
            n = 1
            while name in used:
                n += 1
                name = f"{dist.stage}-{slug(dist.host.key)}-{n}"
            used.add(name)
            remote_type, params = self._transport(dist.host, item)
            wanted = dist.filter or "anything"
            if self._remote_current(item, name, wanted):
                continue
            self.do(
                f"special remote {name} ({remote_type}) in {item.key}, wanted: {wanted}",
                lambda n=name, t=remote_type, p=params, w=wanted: self._remote(item, n, t, p, w),
            )

    def _remote_current(self, item: Item, name: str, wanted: str) -> bool:
        """True when the remote exists with the wanted rule already set."""
        path = self.ws.repo_path(item)
        if not path.exists():
            return False
        repo = Dataset(path).repo
        names = {r.get("name") for r in repo.get_special_remotes().values()}
        return name in names and repo.get_preferred_content("wanted", name) == wanted

    def _transport(self, host: Any, item: Item) -> tuple[str, dict[str, Any]]:
        if host.site_dependent:
            mapping = self.site.mapping(host.key)
            remote_type, params = mapping.type, dict(mapping.parameters)
        elif host.method:
            remote_type, params = host.method, dict(host.parameters)
        else:
            raise BootstrapError(f"host {host.title!r} declares no transfer method")
        if remote_type == "directory" and "directory" in params:
            params["directory"] = str(Path(params["directory"]) / item.repo_name)
        return remote_type, params

    def _remote(self, item: Item, name: str, remote_type: str, params: dict, wanted: str) -> None:
        ds = Dataset(self.ws.repo_path(item))
        repo = ds.repo
        existing = {r.get("name") for r in repo.get_special_remotes().values()}
        if name not in existing:
            if remote_type == "directory":
                Path(params["directory"]).mkdir(parents=True, exist_ok=True)
            options = [f"type={remote_type}", "encryption=none"]
            options += [f"{k}={v}" for k, v in params.items()]
            repo.init_remote(name, options)
        repo.set_preferred_content("wanted", wanted, remote=name)

    # -- study superdataset ------------------------------------------------------------------

    def create_study(self) -> None:
        path = self.ws.study
        if not path.exists():
            self.do("create study superdataset", self._create_study)
        layout = None
        if path.exists():
            layout = study.load(path)
        for item in self.items.values():
            if not item.create:
                continue
            where = self._study_path(item, layout)
            if where is None or (path / where / ".git").exists():
                continue
            self.do(
                f"register {item.key} in the study superdataset at {where}",
                lambda item=item, where=where: self._register(item, where),
            )
        if self.platform is not None and path.exists() and not self.dry:
            self._publish_study()
        elif self.platform is not None and not path.exists():
            self.result.actions.append(f"publish study as {self.group}/{STUDY_REPO}")

    def _publish_study(self) -> None:
        assert self.platform is not None
        study_ds = Dataset(self.ws.study)
        existed = self.platform.get_repository(self.group, STUDY_REPO) is not None
        repo = self._publish(study_ds, STUDY_REPO, STUDY_REPO)
        if not existed:
            self.result.actions.append(f"publish study as {repo.path}")
            self.protect(repo)

    def _study_path(self, item: Item, layout: study.StudyLayout | None) -> str | None:
        layout = layout or study.StudyLayout("", "madmp.json", "sites")
        if item.is_instance:
            return f"{layout.path_of(item.stream)}/{item.instance}"
        return layout.path_of(item.dataset_id)

    def _create_study(self) -> None:
        path = self.ws.study
        try:
            ds = create(str(path), result_renderer="disabled")
            templates.render(self.study_template, ds, {"study_name": self.dmp.title})
            shutil.copy(self.madmp_path, path / "madmp.json")
            if self.sites_dir and self.sites_dir.is_dir():
                for cfg in sorted(self.sites_dir.glob("*.yaml")):
                    shutil.copy(cfg, path / "sites" / cfg.name)
            ds.save(message="Create study superdataset", result_renderer="disabled")
            ds.repo.call_git(["branch", "-M", MAIN])
        except BaseException:
            shutil.rmtree(path, ignore_errors=True)
            raise

    def _register(self, item: Item, where: str) -> None:
        clone(
            source=self.url(item),
            path=str(self.ws.study / where),
            dataset=Dataset(self.ws.study),
            result_renderer="disabled",
        )


def init(
    dmp: Dmp,
    site_config: sites.SiteConfig,
    workspace: Workspace,
    madmp_path: str | Path,
    study_template: str,
    sites_dir: str | Path | None = None,
    dry_run: bool = False,
    platform: Platform | None = None,
    group: str | None = None,
    faire_image: str | None = None,
) -> Result:
    return Bootstrap(
        dmp,
        site_config,
        workspace,
        madmp_path,
        study_template,
        sites_dir,
        dry_run,
        platform,
        group,
        faire_image,
    ).run()
