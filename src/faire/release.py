"""The study release: every dataset is brought to `main` and tagged together (D10).

`release` checks first, and changes nothing unless every check passes:

* consistency: each derived dataset's `sourcedata/` pointers equal the revision of the source
  being released (its `dev`), otherwise the datasets behind are listed;
* `main` of every dataset can be brought to `dev` by fast-forward, so that what is tagged is
  exactly what the derived datasets reference;
* the release identifier is free in every repository.

Then each dataset's `main` is moved to its `dev` and tagged, sources before what is derived from
them, and the study superdataset records the tagged revisions and is tagged in turn. `pilot` is
never merged, so no pilot sample is part of a release.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from datalad.api import Dataset, clone

from faire import containers, plan, sites, study
from faire.model import Dmp
from faire.platform import Platform

DEV, MAIN = "dev", "main"
Locate = Callable[[str], "str | None"]  # repository name -> where it can be cloned from
STUDY_REPO = "study"


class ReleaseError(RuntimeError):
    pass


@dataclass
class Report:
    tag: str
    tagged: dict[str, str] = field(default_factory=dict)  # repository -> released revision
    behind: list[tuple[str, str]] = field(default_factory=list)  # (dataset, source it lags)
    problems: list[str] = field(default_factory=list)
    study_revision: str | None = None
    #: sources declared access-restricted: where they are and the revision referenced
    restricted: list[dict[str, str]] = field(default_factory=list)
    #: components managed outside the study (container collections): never copied
    external: list[dict[str, str]] = field(default_factory=list)
    #: per dataset, its license next to those of the components it references
    licenses: list[dict] = field(default_factory=list)

    @property
    def refused(self) -> bool:
        return bool(self.behind or self.problems)

    def lines(self) -> list[str]:
        out = []
        for dataset, source in self.behind:
            out.append(f"behind: {dataset} references an older state of {source}")
        out += [f"problem: {p}" for p in self.problems]
        if self.refused:
            out.append(f"release {self.tag} refused: nothing was tagged")
            return out
        out += [f"tagged {name} {rev[:12]}" for name, rev in self.tagged.items()]
        for item in self.restricted:
            out.append(
                f"restricted: {item['component']} (source of {item['dataset']}) at "
                f"{item['location']} revision {item['revision'][:12]}"
            )
        for item in self.external:
            out.append(
                f"externally managed: {item['component']} of {item['dataset']} "
                f"({item['containers']}) at {item['location']} revision {item['revision'][:12]}"
            )
        for entry in self.licenses:
            line = f"license: {entry['dataset']} {entry['license'] or 'none declared'}"
            if entry["components"]:
                parts = ", ".join(
                    f"{k} {v or 'none declared'}" for k, v in entry["components"].items()
                )
                line += f" | references: {parts}"
                if any(v != entry["license"] for v in entry["components"].values()):
                    line += " (differ)"
            out.append(line)
        out.append(
            f"study superdataset at {self.study_revision[:12] if self.study_revision else ''}"
        )
        return out


def _git(cwd: Path, *args: str, check: bool = True) -> str:
    out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and out.returncode != 0:
        raise ReleaseError(f"git {' '.join(args)} in {cwd.name}: {out.stderr.strip()}")
    return out.stdout.strip()


@dataclass
class _Repo:
    name: str
    path: Path
    dev: str
    main: str


def _fetch(locate: Locate, name: str, work: Path) -> _Repo:
    url = locate(name)
    if url is None:
        raise ReleaseError(f"{name}: no such repository")
    path = work / name
    subprocess.run(
        ["git", "clone", "--quiet", "--no-checkout", url, str(path)],
        capture_output=True,
        check=True,
    )
    return _Repo(
        name,
        path,
        _git(path, "rev-parse", f"origin/{DEV}"),
        _git(path, "rev-parse", f"origin/{MAIN}"),
    )


def check_consistency(items, repos: dict[str, _Repo]) -> list[tuple[str, str]]:
    """Derived datasets whose pointers differ from the `dev` of the source being released."""
    behind = []
    for item in items:
        if item.key not in repos:
            continue
        for link in item.sources:
            source = repos.get(link.key)
            if source is None:  # an instance at another site: referenced, not released here
                continue
            entry = _git(repos[item.key].path, "ls-tree", f"origin/{DEV}", "--", link.path)
            recorded = entry.split()[2] if entry else None
            if recorded != source.dev:
                behind.append((item.repo_name, repos[link.key].name))
    return behind


def _show(repo: _Repo, path: str) -> str | None:
    out = subprocess.run(
        ["git", "show", f"origin/{DEV}:{path}"], cwd=repo.path, capture_output=True, text=True
    )
    return out.stdout if out.returncode == 0 else None


def _gitlink(repo: _Repo, path: str) -> str | None:
    entry = _git(repo.path, "ls-tree", f"origin/{DEV}", "--", path)
    return entry.split()[2] if entry else None


def _served(location: str, revision: str, scratch: Path) -> bool:
    """Whether the location still has that exact revision (fetching it is the proof)."""
    if not (scratch / "HEAD").exists():
        subprocess.run(["git", "init", "--quiet", "--bare", str(scratch)], check=True)
    done = subprocess.run(
        ["git", "fetch", "--quiet", "--depth", "1", location, revision],
        cwd=scratch,
        capture_output=True,
    )
    return done.returncode == 0


def check_components(items, repos: dict[str, _Repo], dmp: Dmp, report: Report, work: Path) -> None:
    """Every component a dataset references must be released with it, declared restricted, or
    managed elsewhere and still answering for the pinned revision; each is listed in the report."""
    by_key = {i.key: i for i in items}
    scratch = work / "availability.git"
    for item in (i for i in items if i.key in repos):
        repo = repos[item.key]
        dataset = dmp.dataset(item.dataset_id)
        references: dict[str, str | None] = {}
        for link in item.sources:
            revision = _gitlink(repo, link.path)
            if revision is None:  # not installed here: the dataset references nothing of it
                continue
            source = by_key[link.key]
            source_dataset = dmp.dataset(source.dataset_id)
            references[source.repo_name] = source_dataset.license
            if source_dataset.access_restricted:
                report.restricted.append(
                    {
                        "dataset": item.repo_name,
                        "component": source.repo_name,
                        "location": repos[source.key].path.name if source.key in repos else "-",
                        "revision": revision,
                    }
                )
            elif source.key not in repos:
                report.problems.append(
                    f"{item.repo_name}: source {source.repo_name} is neither in this release "
                    "nor declared access-restricted"
                )
        text = _show(repo, containers.DECLARATION)
        if text:
            declared = containers.parse(yaml.safe_load(text) or {})
            for collection in declared.collections:
                revision = _gitlink(repo, collection.path)
                used = ", ".join(
                    c.name for c in declared.containers if c.collection == collection.name
                )
                if revision is None:
                    report.problems.append(
                        f"{item.repo_name}: collection {collection.name} of {used} is not pinned "
                        f"(nothing installed at {collection.path})"
                    )
                elif _served(collection.source, revision, scratch):
                    report.external.append(
                        {
                            "dataset": item.repo_name,
                            "component": collection.name,
                            "containers": used,
                            "location": collection.source,
                            "revision": revision,
                        }
                    )
                else:
                    report.problems.append(
                        f"{item.repo_name}: container {used} of collection {collection.name}: "
                        f"revision {revision[:12]} is no longer served by {collection.source}"
                    )
        report.licenses.append(
            {"dataset": item.repo_name, "license": dataset.license, "components": references}
        )


def on_platform(platform: Platform, group: str) -> Locate:
    def locate(name: str) -> str | None:
        repo = platform.get_repository(group, name)
        return repo.url if repo else None

    return locate


def release(
    platform: Platform | None,
    group: str | None,
    tag: str,
    site: str,
    work: Path | None = None,
    locate: Locate | None = None,
    only: set[str] | None = None,
) -> Report:
    """Release the study held in `group` (or found by `locate`, limited to the repositories
    named in `only`): see the module's description."""
    work = work or Path(tempfile.mkdtemp(prefix="faire-release-"))
    locate = locate or on_platform(platform, group)
    study_url = locate(STUDY_REPO)
    if study_url is None:
        raise ReleaseError(f"{STUDY_REPO}: no study superdataset to release")
    study_ds = clone(source=study_url, path=str(work / STUDY_REPO), result_renderer="disabled")
    study_ds.repo.call_git(["checkout", "-q", "-B", MAIN, f"origin/{MAIN}"])
    dmp = Dmp(json.loads((Path(study_ds.path) / "madmp.json").read_text()))
    layout = study.load(study_ds.path)
    config = sites.load(Path(study_ds.path) / layout.sites / f"{site}.yaml")
    items = plan.creation_plan(dmp, config.site)
    created = [i for i in items if i.create and (only is None or i.repo_name in only)]

    report = Report(tag)
    repos = {i.key: _fetch(locate, i.repo_name, work) for i in created}
    report.behind = check_consistency(items, repos)
    check_components(items, repos, dmp, report, work)
    for item in created:
        repo = repos[item.key]
        existing = _git(repo.path, "ls-remote", "--tags", "origin", tag, check=False)
        if existing and existing.split()[0] != repo.dev:
            report.problems.append(f"{item.repo_name} already has a tag {tag} elsewhere")
        if subprocess.run(
            ["git", "merge-base", "--is-ancestor", repo.main, repo.dev],
            cwd=repo.path,
            capture_output=True,
        ).returncode:
            report.problems.append(f"{item.repo_name}: main has changes dev does not have")
    if report.refused:
        return report

    for item in created:  # sources first: the plan is in provenance order
        repo = repos[item.key]
        _git(repo.path, "push", "--quiet", "origin", f"{repo.dev}:refs/heads/{MAIN}")
        _git(repo.path, "tag", "-f", tag, repo.dev)
        _git(repo.path, "push", "--quiet", "-f", "origin", f"refs/tags/{tag}")
        report.tagged[item.repo_name] = repo.dev

    for item in created:
        where = study.path_for(item, layout)
        _git(
            Path(study_ds.path),
            "update-index",
            "--add",
            "--cacheinfo",
            f"160000,{repos[item.key].dev},{where}",
        )
    study_ds.repo.call_git(["commit", "-q", "--allow-empty", "-m", f"Release {tag}"])
    report.study_revision = study_ds.repo.get_hexsha()
    study_ds.repo.call_git(["tag", "-f", tag])
    study_ds.repo.call_git(["push", "--quiet", "origin", MAIN])
    study_ds.repo.call_git(["push", "--quiet", "-f", "origin", f"refs/tags/{tag}"])
    return report


def checkout_release(platform: Platform, group: str, tag: str, where: Path) -> Dataset:
    """The study superdataset as released at `tag`, with its subdatasets installed."""
    repo = platform.get_repository(group, STUDY_REPO)
    ds = clone(source=repo.url, path=str(where), result_renderer="disabled")
    ds.repo.call_git(["checkout", "-q", tag])
    ds.get(".", get_data=False, recursive=True, result_renderer="disabled")
    return ds
