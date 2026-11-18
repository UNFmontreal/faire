"""Archival: the study as a copy that needs no DevOps platform (D13, D24).

For every repository of the study (the datasets, the instrument instances and the study
superdataset) the archival host receives the version history and, for each release, the content
the dataset's archival distributions select, through the same fulfilment as any distribution.

The archived references between repositories must resolve from the archive alone. History is
never rewritten: a commit that references other repositories gets a child commit whose
`.gitmodules` points to its siblings by relative address (`../<repository>.git`) and whose
pointers are those of the siblings' own archived commits. The archive's branches and release tags
are these child commits, so cloning the archived study superdataset and installing everything
below it never leaves the archive.

The archive keeps one bare repository per repository, `<archive>/<repository>.git`, next to the
content the distribution put in `<archive>/<repository>`; both are found from the archival
distribution's host, which must be a directory (other hosts are reported, not guessed).
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from datalad.api import Dataset

from faire import distribution, identity, plan, sites, study
from faire.model import Dmp

BRANCHES = ("main", "dev")
STUDY_REPO = "study"


class ArchiveError(RuntimeError):
    pass


@dataclass
class Report:
    archived: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    content: list[distribution.Outcome] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems and all(o.ok for o in self.content)


def _git(path: Path, *args: str, env: dict | None = None, check: bool = True) -> str:
    out = subprocess.run(
        ["git", *args], cwd=path, capture_output=True, text=True, env={**os.environ, **(env or {})}
    )
    if check and out.returncode != 0:
        raise ArchiveError(f"git {' '.join(args)} in {path.name}: {out.stderr.strip()}")
    return out.stdout.strip()


class _Rewriter:
    """The archived commit of a commit: itself, or a child pointing to its siblings' archives."""

    def __init__(self, paths: dict[str, Path], links: dict[str, dict[str, str]]):
        self.paths = paths  # repository -> its clone
        self.links = links  # repository -> {path of a pointer: repository it points to}
        self.done: dict[tuple[str, str], str] = {}
        who = identity.from_environment()
        self.env = {
            "GIT_AUTHOR_NAME": who.name,
            "GIT_AUTHOR_EMAIL": who.email,
            "GIT_COMMITTER_NAME": who.name,
            "GIT_COMMITTER_EMAIL": who.email,
        }

    def __call__(self, name: str, commit: str) -> str:
        key = (name, commit)
        if key not in self.done:
            self.done[key] = self._rewrite(name, commit)
        return self.done[key]

    def _has(self, name: str, commit: str) -> bool:
        found = subprocess.run(
            ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
            cwd=self.paths[name],
            capture_output=True,
        )
        return found.returncode == 0

    def _rewrite(self, name: str, commit: str) -> str:
        where, links = self.paths[name], self.links.get(name) or {}
        if not links:
            return commit
        with tempfile.TemporaryDirectory() as scratch:
            index = {"GIT_INDEX_FILE": str(Path(scratch) / "index"), **self.env}
            _git(where, "read-tree", commit, env=index)
            tree_before = _git(where, "write-tree", env=index)
            modules = _git(where, "show", f"{commit}:.gitmodules", check=False)
            if modules:
                file = Path(scratch) / "gitmodules"
                file.write_text(modules + "\n")
                section = {
                    line.split(" ", 1)[1]: line.split(" ", 1)[0][len("submodule.") : -len(".path")]
                    for line in _git(
                        where, "config", "-f", str(file), "--get-regexp", r"^submodule\..*\.path$"
                    ).splitlines()
                }
                for pointer, source in links.items():
                    if pointer in section:
                        key = f"submodule.{section[pointer]}.url"
                        _git(where, "config", "-f", str(file), key, f"../{source}.git")
                        _git(
                            where, "config", "-f", str(file), "--unset-all",
                            f"submodule.{section[pointer]}.datalad-url", check=False,
                        )  # fmt: skip
                blob = _git(where, "hash-object", "-w", str(file))
                _git(
                    where,
                    "update-index",
                    "--add",
                    "--cacheinfo",
                    f"100644,{blob},.gitmodules",
                    env=index,
                )
            for pointer, source in links.items():
                entry = _git(where, "ls-tree", commit, "--", pointer)
                if not entry.startswith("160000"):
                    continue
                old = entry.split()[2]
                new = self(source, old) if self._has(source, old) else old
                if new != old:
                    _git(where, "update-index", "--cacheinfo", f"160000,{new},{pointer}", env=index)
            tree = _git(where, "write-tree", env=index)
            if tree == tree_before:
                return commit
            message = "Archive: references to the other repositories are relative"
            return _git(where, "commit-tree", tree, "-p", commit, "-m", message, env=self.env)


def _archive_root(dmp: Dmp, site: sites.SiteConfig) -> Path:
    """Where the archive lives: the directory of the archival hosts (all in one place)."""
    roots = set()
    for dataset in dmp.datasets:
        for dist in dataset.distributions_at("archival"):
            host = dist.host
            if host is None:
                continue
            mapping = site.mapping(host.key) if host.site_dependent else None
            method = mapping.type if mapping else host.method
            params = mapping.parameters if mapping else host.parameters
            if method != "directory" or "directory" not in params:
                raise ArchiveError(
                    f"archival host {host.title!r}: only directory hosts hold history here"
                )
            roots.add(Path(params["directory"]))
    if not roots:
        raise ArchiveError("the ma-DMP declares no archival distribution")
    if len(roots) > 1:
        raise ArchiveError("the archival hosts must share one directory for references to resolve")
    return roots.pop()


def archive(workspace: Path, dmp: Dmp, site: sites.SiteConfig) -> Report:
    """Archive every repository of the workspace: content of each release, then history."""
    report = Report()
    root = _archive_root(dmp, site)
    root.mkdir(parents=True, exist_ok=True)
    layout = study.load(Path(workspace) / "study")
    items = [i for i in plan.creation_plan(dmp, site.site) if i.create]
    by_key = {i.key: i for i in items}
    paths = {i.repo_name: Path(workspace) / "repos" / i.repo_name for i in items}
    paths[STUDY_REPO] = Path(workspace) / "study"
    links = {
        i.repo_name: {s.path: by_key[s.key].repo_name for s in i.sources if s.key in by_key}
        for i in items
    }
    links[STUDY_REPO] = {study.path_for(i, layout): i.repo_name for i in items}

    for path in paths.values():
        if "origin" in Dataset(path).repo.get_remotes():
            _git(path, "fetch", "-q", "--recurse-submodules=no", "--tags", "origin")
    tags = _git(paths[STUDY_REPO], "tag", "--list").split()
    report.tags = tags
    for item in items:
        dataset = dmp.dataset(item.dataset_id)
        if dataset.distributions_at("archival"):
            report.content += _content(Dataset(paths[item.repo_name]), dataset, item, site, tags)

    rewrite = _Rewriter(paths, links)
    for name, path in paths.items():
        target = root / f"{name}.git"
        if not target.exists():
            _git(root, "init", "-q", "--bare", str(target))
        refspecs = []
        for tag in tags:
            if _git(
                path, "rev-parse", "-q", "--verify", f"refs/tags/{tag}^{{commit}}", check=False
            ):
                commit = _git(path, "rev-parse", f"refs/tags/{tag}^{{commit}}")
                refspecs.append(f"{rewrite(name, commit)}:refs/tags/{tag}")
        for branch in BRANCHES:
            commit = ""  # what the platform holds, else what is here
            for ref in (f"refs/remotes/origin/{branch}", f"refs/heads/{branch}"):
                commit = commit or _git(path, "rev-parse", "-q", "--verify", ref, check=False)
            if commit:
                refspecs.append(f"{rewrite(name, commit)}:refs/heads/{branch}")
        if "git-annex" in Dataset(path).repo.get_branches():
            refspecs.append("refs/heads/git-annex:refs/heads/git-annex")
        if refspecs:
            _git(path, "push", "-q", "-f", str(target), *refspecs)
            _git(target, "symbolic-ref", "HEAD", "refs/heads/main", check=False)
        report.archived.append(name)
    return report


def _content(ds: Dataset, dataset, item, site, tags: list[str]) -> list[distribution.Outcome]:
    """What the archival distributions select, at each release, to the archival host."""
    outcomes: list[distribution.Outcome] = []
    repo = ds.repo
    previous = repo.get_active_branch()
    for tag in tags:
        if not repo.call_git_success(["rev-parse", "-q", "--verify", f"refs/tags/{tag}"]):
            continue
        repo.call_git(["checkout", "-q", "-B", "faire-archive", f"refs/tags/{tag}"])
        try:
            for dist in dataset.distributions_at("archival"):
                wanted = dist.filter or "anything"
                files = distribution.selected(ds, wanted)
                if files:
                    ds.get(files, result_renderer="disabled", on_failure="ignore")
            outcomes += distribution.fulfil(ds, dataset, item.repo_name, site, "archival")
        finally:
            repo.call_git(["checkout", "-q", previous])
            repo.call_git(["branch", "-q", "-D", "faire-archive"])
    return outcomes
