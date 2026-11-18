"""Federation: a site and the hub exchange history through the datasets' two-way distributions.

`exchange` brings one repository of the site and its copy on the hub to the same state, branch by
branch (`dev`, `main`, `pilot`): what is only on one side is copied, what diverged is merged.
The merge keeps to what the template declared (union merges in `.gitattributes`) and settles a
`sourcedata/` pointer by ancestry, never by date; any other conflict stops that repository,
changes neither side and is reported. `sync_all` does this for every federated repository in
provenance order, so a source is settled before what is derived from it.

Only history and git-annex's location records travel to the hub. Content goes to the hub's
storage when the site configuration names one, filtered like any distribution; with a git-only
hub other sites learn from the location records which site holds a file.
"""

from __future__ import annotations

import contextlib
import json
import subprocess
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from datalad.api import Dataset, clone

from faire import distribution, identity, plan, release, remotes, sites
from faire.model import Dmp

HUB = "hub"
BRANCHES = ("dev", "main", "pilot")
STUDY_REPO = "study"
GITLINK = "160000"
SITE_HEADS = "refs/faire/sites"

#: (path of a pointer, branch, ours, theirs) -> the revision the merged repository should hold
Resolver = Callable[[str, str, str, str], "str | None"]


class FederationError(RuntimeError):
    pass


@dataclass
class Exchange:
    repository: str
    pushed: list[str] = field(default_factory=list)  # branches the hub received
    updated: list[str] = field(default_factory=list)  # branches that moved here
    conflicts: list[str] = field(default_factory=list)  # `branch: path` left for a person

    @property
    def ok(self) -> bool:
        return not self.conflicts

    def describe(self) -> str:
        if self.conflicts:
            return f"{self.repository}: not synchronised, conflict in " + ", ".join(self.conflicts)
        return f"{self.repository}: in step with the hub"

    @property
    def changed(self) -> bool:
        return bool(self.pushed or self.updated)


def _ancestor(repo, older: str, newer: str) -> bool:
    return repo.call_git_success(["merge-base", "--is-ancestor", older, newer])


def _rev(repo, ref: str) -> str | None:
    return (
        repo.call_git_oneline(["rev-parse", "--verify", "-q", ref])
        if repo.call_git_success(["rev-parse", "--verify", "-q", ref])
        else None
    )


@contextlib.contextmanager
def _on(repo, branch: str) -> Iterator[None]:
    previous = repo.get_active_branch()
    if previous != branch:
        repo.call_git(["checkout", "-q", branch])
    try:
        yield
    finally:
        if previous and previous != branch:
            repo.call_git(["checkout", "-q", previous])


def _merge(repo, branch: str, theirs: str, resolve: Resolver | None, out: Exchange) -> bool:
    """Merge `theirs` into the checked-out `branch`; False (nothing changed) on a conflict."""
    if repo.call_git_success(["merge", "-q", "--no-edit", theirs]):
        return True
    unmerged: dict[str, dict[str, tuple[str, str]]] = {}
    for line in repo.call_git(["ls-files", "-u"]).splitlines():
        meta, path = line.split("\t", 1)
        mode, sha, stage = meta.split()
        unmerged.setdefault(path, {})[stage] = (mode, sha)
    for path, stages in unmerged.items():
        ours, theirs_ = stages.get("2"), stages.get("3")
        picked = None
        if ours and theirs_ and ours[0] == theirs_[0] == GITLINK and resolve:
            picked = resolve(path, branch, ours[1], theirs_[1])
        if picked is None:
            out.conflicts.append(f"{branch}: {path}")
            continue
        repo.call_git(["update-index", "--add", "--cacheinfo", f"{GITLINK},{picked},{path}"])
    if out.conflicts:
        repo.call_git(["merge", "--abort"])
        return False
    repo.call_git(["commit", "-q", "--no-edit"])
    return True


def _branch(repo, branch: str, site: str, resolve: Resolver | None, out: Exchange) -> None:
    mine = _rev(repo, f"refs/heads/{branch}")
    theirs = _rev(repo, f"refs/remotes/{HUB}/{branch}")
    if mine == theirs:
        return
    if theirs is None:
        repo.call_git(["push", "-q", HUB, f"refs/heads/{branch}"])
        out.pushed.append(branch)
        return
    if mine is None:
        repo.call_git(["branch", branch, theirs])
        out.updated.append(branch)
        return
    if _ancestor(repo, theirs, mine):
        repo.call_git(["push", "-q", HUB, f"refs/heads/{branch}"])
        out.pushed.append(branch)
        return
    if _ancestor(repo, mine, theirs):
        with _on(repo, branch):
            repo.call_git(["merge", "-q", "--ff-only", theirs])
        out.updated.append(branch)
        return
    # both sides moved: say what this site holds (so the coordinator can tell it is not yet
    # on the hub if the merge cannot be completed), then merge
    repo.call_git(["push", "-q", "-f", HUB, f"refs/heads/{branch}:{SITE_HEADS}/{site}/{branch}"])
    with _on(repo, branch):
        merged = _merge(repo, branch, theirs, resolve, out)
    if not merged:
        return
    repo.call_git(["push", "-q", HUB, f"refs/heads/{branch}"])
    out.updated.append(branch)
    out.pushed.append(branch)


def exchange(
    ds: Dataset,
    site: sites.SiteConfig,
    repository: str,
    resolve: Resolver | None = None,
    dataset=None,
) -> Exchange:
    """Bring `ds` and its copy on the hub to the same state."""
    out = Exchange(repository)
    repo = ds.repo
    identity.apply(ds, identity.from_environment())
    url = site.hub_repository(repository)
    if HUB not in repo.get_remotes():
        repo.call_git(["remote", "add", HUB, url])
    repo.call_git(["fetch", "-q", "--recurse-submodules=no", "--tags", HUB])
    for branch in BRANCHES:
        _branch(repo, branch, site.site, resolve, out)
    if not out.ok:
        return out  # nothing of this repository is left half done
    if _rev(repo, f"refs/remotes/{HUB}/git-annex"):
        repo.call_annex(["merge"])
    here = f"{site.site} ({repository})"
    if "git-annex" in repo.get_branches():
        known = (repo.call_annex_records(["info", "--fast", "here"]) or [{}])[0]
        if known.get("description", "").removesuffix(" [here]") != here:
            repo.call_annex(["describe", "here", here])  # other sites can tell whose it is
        repo.call_git(["push", "-q", HUB, "git-annex"])
    if dataset is not None and site.hub_storage:
        _to_hub_storage(ds, site, repository, dataset)
    return out


def _to_hub_storage(ds: Dataset, site: sites.SiteConfig, repository: str, dataset) -> None:
    """Non-sensitive, non-pilot content to the hub's storage, where the hub has storage."""
    dist = dataset.hub_distribution
    storage = site.hub_storage
    params = dict(storage.parameters)
    if storage.type == "directory" and "directory" in params:
        params["directory"] = str(Path(params["directory"]) / repository)
    wanted = f"({dist.filter or 'anything'}) and not metadata={remotes.RESTRICTIONS}=pilot"
    spec = remotes.RemoteSpec("hub-storage", "accepted", storage.type, params, wanted)
    distribution._ensure_remote(ds, spec)
    ds.push(to=spec.name, data="auto", result_renderer="disabled", on_failure="ignore")


def pointer_resolver(source_repos: dict[str, Path]) -> Resolver:
    """Settle a `sourcedata/` pointer: the descendant wins; when neither descends from the other,
    the source's own head, which has both, is used. `source_repos` maps a pointer's path to the
    repository of the source at this site."""

    def resolve(path: str, branch: str, ours: str, theirs: str) -> str | None:
        where = source_repos.get(path)
        if where is None or not where.exists():
            return None
        repo = Dataset(where).repo
        if _ancestor(repo, ours, theirs):
            return theirs
        if _ancestor(repo, theirs, ours):
            return ours
        head = _rev(repo, f"refs/heads/{branch}")
        if head and _ancestor(repo, ours, head) and _ancestor(repo, theirs, head):
            return head
        return None

    return resolve


def sync_all(
    workspace: Path, dmp: Dmp, site: sites.SiteConfig, only: set[str] | None = None
) -> list[Exchange]:
    """Exchange every federated repository of this site with the hub, sources first, then the
    study superdataset (which carries the ma-DMP and the site configurations)."""
    items = plan.creation_plan(dmp, site.site)
    by_key = {i.key: i for i in items}
    repos = Path(workspace) / "repos"
    done: list[Exchange] = []
    for item in items:
        dataset = dmp.dataset(item.dataset_id)
        path = repos / item.repo_name
        if not (item.create and dataset.hub_distribution and path.exists()):
            continue
        if only and item.repo_name not in only:
            continue
        pointers = {
            link.path: repos / by_key[link.key].repo_name
            for link in item.sources
            if by_key[link.key].create
        }
        done.append(
            exchange(Dataset(path), site, item.repo_name, pointer_resolver(pointers), dataset)
        )
    study = Path(workspace) / "study"
    if study.exists() and not (only and STUDY_REPO not in only):
        done.append(exchange(Dataset(study), site, STUDY_REPO))
    return done


def hub_has(site: sites.SiteConfig, repository: str) -> bool:
    """Whether the hub holds this repository (a site joining installs it from there)."""
    found = subprocess.run(
        ["git", "ls-remote", site.hub_repository(repository)], capture_output=True, text=True
    )
    return found.returncode == 0 and bool(found.stdout.strip())


def install(url: str, path: Path, remote: str = HUB) -> Dataset:
    """A copy of a repository with the origin named `remote` and a local branch for each of ours."""
    ds = clone(url, str(path), result_renderer="disabled")
    repo = ds.repo
    if remote != "origin":
        repo.call_git(["remote", "rename", "origin", remote])
    for branch in BRANCHES:
        if _rev(repo, f"refs/remotes/{remote}/{branch}") and branch not in repo.get_branches():
            repo.call_git(["branch", branch, f"{remote}/{branch}"])
    return ds


def install_from_hub(site: sites.SiteConfig, repository: str, path: Path) -> Dataset:
    return install(site.hub_repository(repository), path)


# -- coordinated release and archival ----------------------------------------------------------


def _federated(workspace: Path, dmp: Dmp, site: sites.SiteConfig) -> dict[str, tuple]:
    """The federated repositories this site holds: repository name -> (dataset, ma-DMP dataset)."""
    found = {}
    for item in plan.creation_plan(dmp, site.site):
        dataset = dmp.dataset(item.dataset_id)
        path = Path(workspace) / "repos" / item.repo_name
        if item.create and dataset.hub_distribution and path.exists():
            found[item.repo_name] = (Dataset(path), dataset)
    return found


def lagging_sites(workspace: Path, dmp: Dmp, site: sites.SiteConfig) -> list[str]:
    """Sites (this one included) holding accepted work the hub does not have: what each site last
    said it held (`announced` before a merge) or holds now must be in the hub's `dev`."""
    behind: set[str] = set()
    repos = {name: ds for name, (ds, _d) in _federated(workspace, dmp, site).items()}
    study = Path(workspace) / "study"
    if study.exists():
        repos[STUDY_REPO] = Dataset(study)
    for ds in repos.values():
        repo = ds.repo
        repo.call_git(
            ["fetch", "-q", "--recurse-submodules=no", HUB, f"+{SITE_HEADS}/*:refs/faire/seen/*"]
        )
        hub_dev = _rev(repo, f"refs/remotes/{HUB}/dev")
        mine = _rev(repo, "refs/heads/dev")
        if hub_dev and mine and not _ancestor(repo, mine, hub_dev):
            behind.add(site.site)
        for line in repo.call_git(
            ["for-each-ref", "--format=%(refname) %(objectname)", "refs/faire/seen/"]
        ).splitlines():
            ref, sha = line.split()
            _, _, _, who, branch = ref.split("/", 4)
            if branch == "dev" and hub_dev and not _ancestor(repo, sha, hub_dev):
                behind.add(who)
    return sorted(behind)


def start_release(
    workspace: Path, dmp: Dmp, site: sites.SiteConfig, tag: str, work: Path | None = None
) -> release.Report:
    """The coordinator's release of the federated repositories, through the hub."""
    if dmp.coordinator != site.site:
        raise FederationError(
            f"site {site.site!r} is not the coordinator: only {dmp.coordinator!r} starts a release"
        )
    behind = lagging_sites(workspace, dmp, site)
    if behind:
        report = release.Report(tag)
        report.problems = [f"site {who} has accepted work the hub does not hold" for who in behind]
        return report
    names = set(_federated(workspace, dmp, site)) | {STUDY_REPO}
    return release.release(None, None, tag, site.site, work, locate=site.hub_repository, only=names)


def deliver(
    workspace: Path, dmp: Dmp, site: sites.SiteConfig, tag: str, stage: str = "release"
) -> list[distribution.Outcome]:
    """Bring the tag from the hub and transfer the files of it this site holds to the hosts of
    the stage. Nothing is written to the ma-DMP here: that is the coordinator's."""
    outcomes: list[distribution.Outcome] = []
    for name, (ds, dataset) in _federated(workspace, dmp, site).items():
        exchange(ds, site, name, None, dataset)
        repo = ds.repo
        if not _rev(repo, f"refs/tags/{tag}"):
            continue
        previous = repo.get_active_branch()
        repo.call_git(["checkout", "-q", "-B", "faire-deliver", f"refs/tags/{tag}"])
        try:
            outcomes += distribution.fulfil(ds, dataset, name, site, stage)
        finally:
            repo.call_git(["checkout", "-q", previous])
            repo.call_git(["branch", "-q", "-D", "faire-deliver"])
        exchange(ds, site, name, None, dataset)  # share where the files are now
    return outcomes


def owing(ds: Dataset, spec: remotes.RemoteSpec) -> list[str]:
    """Sites whose repositories hold files the host still lacks, by git-annex's records."""
    uuid = distribution._uuid(ds, spec.name)
    who: set[str] = set()
    for line in distribution._annex(ds, "whereis", "--json").stdout.splitlines():
        entry = json.loads(line)
        held = entry.get("whereis", [])
        if uuid in {w.get("uuid") for w in held}:
            continue
        who |= {w["description"].split(" (")[0] for w in held if " (" in w.get("description", "")}
    return sorted(who)


def finish(
    workspace: Path,
    dmp: Dmp,
    site: sites.SiteConfig,
    tag: str,
    study: Dataset,
    stage: str = "release",
) -> list[str]:
    """The coordinator's completion: once every selected file is on the host, obtain the
    identifiers and write the facts to the ma-DMP. Until then, say which sites owe files."""
    if dmp.coordinator != site.site:
        raise FederationError(f"only the coordinator {dmp.coordinator!r} completes a {stage}")
    lines: list[str] = []
    for name, (ds, dataset) in _federated(workspace, dmp, site).items():
        exchange(ds, site, name, None, dataset)
        previous = ds.repo.get_active_branch()
        ds.repo.call_git(["checkout", "-q", "-B", "faire-deliver", f"refs/tags/{tag}"])
        try:
            outcomes = []
            for dist, spec in remotes.distribution_specs(dataset, name, site, stages=(stage,)):
                if spec.name not in remotes.names(ds):
                    outcomes.append(distribution.Outcome(dist.title, "incomplete", "", spec.name))
                    continue
                if not remotes.is_enabled(ds, spec.name):
                    remotes.enable(ds, spec)
                missing = distribution.missing_on(ds, spec.name, spec.wanted)
                outcomes.append(
                    distribution.Outcome(
                        dist.title,
                        "incomplete" if missing else "done",
                        "",
                        spec.name,
                        missing=missing,
                        size=distribution._size(ds, spec.name),
                    )
                )
                if missing:
                    lines.append(
                        f"{name}: {dist.title} lacks files; owed by " + ", ".join(owing(ds, spec))
                    )
            lines += distribution.complete(ds, dataset, stage, outcomes, study, tag)
        finally:
            ds.repo.call_git(["checkout", "-q", previous])
            ds.repo.call_git(["branch", "-q", "-D", "faire-deliver"])
    return lines
