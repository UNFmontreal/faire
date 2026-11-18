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

from faire import containers, federation, plan, remotes, sites, study, templates
from faire.model import Dmp
from faire.plan import Item
from faire.platform import Platform, Repository

RECORD = ".faire/dataset.yaml"
BRANCHES = ("dev", "pilot", "main")
EARLY_STAGES = remotes.EARLY_STAGES
MAIN = "main"
PROTECTED_BRANCHES = ("dev", "pilot", "main")
SAMPLE_BRANCHES = "feature/*"  # branches the tool opens for samples; may read task secrets
REQUIRED_OPERATIONS = (
    "ensure_group",
    "ensure_repository",
    "protect_branch",
    "protect_tag",
    "set_merge_policy",
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


slug = remotes.slug


def protect_repository(platform: Platform, repo: Repository) -> list[str]:
    """Protect a repository the way every dataset repository is; return what could not be."""
    notes: list[str] = []
    for pattern in PROTECTED_BRANCHES:
        result = platform.protect_branch(repo, pattern, approvals=1)
        notes += [n for n in result.notes if n not in notes]
    platform.protect_branch(repo, SAMPLE_BRANCHES, approvals=0)
    platform.protect_tag(repo, "*")
    platform.set_merge_policy(repo)
    return notes


def propose_registration(
    ds: Dataset, branch: str, link: dict[str, Any], source_url: str, instance: str | None
) -> None:
    """Register an instrument instance as a source of a derived dataset, on a branch.

    The change is made on `branch` (from `dev`), to be reviewed through a pull request; the
    dataset's own branches are left untouched and the checked-out branch is restored.
    """
    repo = ds.repo
    previous = repo.get_active_branch()
    repo.call_git(["branch", branch, "dev"])
    repo.checkout(branch)
    try:
        clone(
            source=source_url,
            path=str(Path(ds.path) / link["path"]),
            dataset=ds,
            result_renderer="disabled",
        )
        record = Path(ds.path) / RECORD
        data = yaml.safe_load(record.read_text())
        data["sources"].append(link)
        record.write_text(yaml.safe_dump(data, sort_keys=False))
        title = f"Register instrument instance {instance}"
        ds.save(
            message=f"{title}\n\nfaire-register-instance: {instance}", result_renderer="disabled"
        )
    finally:
        repo.checkout(previous)


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
        self.joined: set[str] = set()  # federated datasets installed from the hub

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
        self.join_from_hub()
        for item in self.items.values():
            if not item.create:
                self.result.skipped.append(
                    f"{item.key}: instance of site {item.site!r}, referenced not created"
                )
                continue
            if self.ws.repo_path(item).exists():
                if not self.reconcile_existing(item):
                    continue
                if item.key in self.joined:  # own instruments join the history received
                    self.register_own_instances(item)
                self.publish_if_missing(item)
            else:
                self.create_dataset(item)
                self.install_sources(item)
                self.publish_new(item)
            self.configure_remotes(item)
            self.publish_annex_state(item)
            self.configure_platform(item)
        self.report_unplanned()
        self.create_study()
        self.report_missing_secrets()
        return self.result

    def join_from_hub(self) -> None:
        """A federated dataset the hub already holds, or any dataset a shared platform already
        holds, is installed from there instead of being created again."""
        for item in self.items.values():
            dataset = self.dmp.dataset(item.dataset_id)
            path = self.ws.repo_path(item)
            if not item.create or path.exists():
                continue
            if (
                self.site.hub_url
                and dataset.hub_distribution
                and federation.hub_has(self.site, item.repo_name)
            ):
                self.joined.add(item.key)
                self.do(
                    f"install {item.key} from the hub",
                    lambda item=item, path=path: federation.install_from_hub(
                        self.site, item.repo_name, path
                    ),
                )
            elif self.platform is not None:
                repo = self.platform.get_repository(self.group, item.repo_name)
                if repo is not None:
                    self.joined.add(item.key)
                    self.do(
                        f"install {item.key} from {repo.path}",
                        lambda repo=repo, path=path: federation.install(repo.url, path, "origin"),
                    )

    def _on_platform(self, name: str) -> bool:
        return self.platform is not None and self.platform.get_repository(self.group, name)

    def register_own_instances(self, item: Item) -> None:
        """Instances of this site's instruments join a dataset received from elsewhere: directly
        where nothing protects its branches, as a proposal where a platform does."""
        for link in item.sources:
            source = self.items[link.key]
            path = self.ws.repo_path(item)
            seen = Dataset(path).repo.call_git(["ls-tree", "main", "--", link.path]).strip()
            if not source.create or seen or not self.exists(source):
                continue
            if self.platform is None:
                self._install(path, link.path, source)
                self._align_branches(item)
            else:
                spec = {"path": link.path, "key": link.key, "role": link.role}
                self.register_instance(item, source, spec)

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
        self._push_state(ds)
        # the git-annex branch is synchronised by the push above, which merges what the
        # remote holds; pushing it again as a plain branch is rejected once the remote moved
        branches = [
            b for b in ds.repo.get_branches() if b not in (ds.repo.get_active_branch(), "git-annex")
        ]
        if branches:
            ds.repo.push(remote="origin", refspec=branches)
        return repo

    @staticmethod
    def _push_state(ds: Dataset) -> None:
        """Push the checked-out branch and the git-annex branch to `origin`."""
        # git-annex may write to the remote while the push updates availability information,
        # which makes the first attempt on the git-annex branch a non-fast-forward; the second
        # attempt merges it
        failed = ds.push(
            to="origin", data="nothing", result_renderer="disabled", on_failure="ignore"
        )
        if any(r.get("status") not in ("ok", "notneeded") for r in failed):
            ds.push(to="origin", data="nothing", result_renderer="disabled")

    def publish_annex_state(self, item: Item) -> None:
        """Make the special remotes created after publication known to the platform's copy, so
        that a fresh clone can enable them."""
        path = self.ws.repo_path(item)
        if self.platform is None or self.dry or not path.exists():
            return
        ds = Dataset(path)
        if "origin" in ds.repo.get_remotes():
            self._push_state(ds)

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
        for note in protect_repository(self.platform, repo):
            if note not in self.result.notes:
                self.result.notes.append(note)

    def variables_for(self, item: Item) -> dict[str, str]:
        """CI variables derived from the ma-DMP: sources, downstream datasets, secret names."""
        downstream = sorted(
            {
                other.repo_name
                for other in self.items.values()
                if any(link.key == item.key and link.triggering for link in other.sources)
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
        propose_registration(
            Dataset(self.ws.repo_path(item)), branch, link, self.url(source), source.instance
        )

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
                # sources that are instrument streams hold one folder per instrument
                "source_instance_glob": (
                    "*/" if any(len(Path(s.path).parts) == 3 for s in item.sources) else ""
                ),
            }
            templates.render(tpl.repository, ds, data, tpl.version)
            record = Path(ds.path) / RECORD
            record.parent.mkdir(parents=True, exist_ok=True)
            record.write_text(yaml.safe_dump(record_for(self.dmp, item), sort_keys=False))
            try:
                containers.register(ds)
            except containers.ContainerError as exc:
                raise BootstrapError(f"{item.key} is not created: {exc}") from exc
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

    def _align_branches(self, item: Item) -> None:
        """Let `dev` and `pilot` have what `main` gained since they were created (the sources),
        as long as they have not moved on their own."""
        path = self.ws.repo_path(item)
        if self.dry or not path.exists():
            return
        repo = Dataset(path).repo
        for branch in BRANCHES:
            if branch == MAIN or branch not in repo.get_branches():
                continue
            try:
                repo.call_git(["merge-base", "--is-ancestor", branch, MAIN])
            except Exception:
                continue  # it has commits of its own: leave it
            repo.call_git(["branch", "-f", branch, MAIN])

    def install_sources(self, item: Item) -> None:
        self._install_sources(item)
        self._align_branches(item)

    def _install_sources(self, item: Item) -> None:
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
        try:
            wanted = remotes.specs(dataset, item.repo_name, self.site)
        except (remotes.RemoteError, sites.SiteConfigError) as exc:
            raise BootstrapError(str(exc)) from exc
        for spec in wanted:
            if self._remote_current(item, spec):
                continue
            self.do(
                f"special remote {spec.name} ({spec.type}) in {item.key}, wanted: {spec.wanted}",
                lambda spec=spec: remotes.create(Dataset(self.ws.repo_path(item)), spec),
            )

    def _remote_current(self, item: Item, spec: remotes.RemoteSpec) -> bool:
        path = self.ws.repo_path(item)
        return path.exists() and remotes.current(Dataset(path), spec)

    # -- study superdataset ------------------------------------------------------------------

    def create_study(self) -> None:
        path = self.ws.study
        if not path.exists() and self.site.hub_url and federation.hub_has(self.site, STUDY_REPO):
            self.do(
                "install the study superdataset from the hub",
                lambda: federation.install_from_hub(self.site, STUDY_REPO, path),
            )
        elif not path.exists() and self._on_platform(STUDY_REPO):
            repo = self.platform.get_repository(self.group, STUDY_REPO)
            self.do(
                "install the study superdataset from the platform",
                lambda: federation.install(repo.url, path, "origin"),
            )
        elif not path.exists():
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
        # the study's validation pipeline runs in the tool's image
        if self.faire_image and self.platform.get_variables(repo).get("FAIRE_IMAGE") != (
            self.faire_image
        ):
            self.do(
                f"set CI variable FAIRE_IMAGE on {repo.path}",
                lambda: self.platform.set_variable(repo, "FAIRE_IMAGE", self.faire_image),
            )

    def _study_path(self, item: Item, layout: study.StudyLayout | None) -> str | None:
        return study.path_for(item, layout)

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
