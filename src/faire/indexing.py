"""Indexing: bring a directory of received files into an instrument's source dataset.

`index` works in a fresh clone of the repository of the instrument that produced the files. The
study's heuristic (`.faire/heuristic.py` of that clone) decides what the files mean; the files are
then recorded as a sample, their content goes to the instance's `collection` storage, and only
afterwards the history is pushed, so that no pushed revision refers to content that is not there.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import tarfile
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from datalad.api import Dataset, clone

from faire import bootstrap, plan, remotes, sites, undeclared
from faire import heuristic as heur
from faire import trigger as triggering
from faire.model import Dmp
from faire.platform import Platform

RESTRICTIONS = "distribution-restrictions"  # git-annex metadata field the wanted rules read
SENSITIVE, PILOT = "sensitive", "pilot"
DEFAULT_BRANCH, PILOT_BRANCH = "dev", "pilot"
CONFIG = ".faire/indexing.yaml"  # `archive: true` packs each sample into archives on storage
ARCHIVES = ".faire/archives"


class IndexingError(RuntimeError):
    pass


class Repositories:
    """Where the study's repositories are: on the platform, or in a local workspace."""

    def __init__(
        self,
        platform: Platform | None = None,
        group: str | None = None,
        root: str | Path | None = None,
    ):
        self.platform, self.group = platform, group
        self.root = Path(root).resolve() / "repos" if root else None

    def url(self, name: str) -> str:
        if self.platform is not None:
            repo = self.platform.get_repository(self.group, name)
            if repo is None:
                raise IndexingError(f"{self.group}/{name}: no such repository on the platform")
            return repo.url
        if self.root is None or not (self.root / name).exists():
            raise IndexingError(f"{name}: no such repository in the workspace")
        return str(self.root / name)

    def exists(self, name: str) -> bool:
        if self.platform is not None:
            return self.platform.get_repository(self.group, name) is not None
        return self.root is not None and (self.root / name).exists()

    def ensure(self, name: str) -> str:
        """Create a repository like the others (protected, merge policy) and return its url."""
        if self.platform is None:
            raise IndexingError(
                f"{name}: creating a repository needs a platform (a local workspace has none)"
            )
        repo = self.platform.ensure_repository(self.group, name)
        bootstrap.protect_repository(self.platform, repo)
        return repo.url


@dataclass
class Request:
    incoming: Path
    stream: str
    dmp: Dmp
    site: sites.SiteConfig
    repositories: Repositories
    workdir: Path | None = None  # where the clone is made; a temporary folder by default
    instrument: str | None = None  # names the instrument when the heuristic does not
    dry_run: bool = False
    env: Mapping[str, str] | None = None  # where credentials come from; the process's if None
    trigger: bool = True  # start the derived datasets' pipelines once the sample is pushed


@dataclass
class Result:
    entities: dict[str, str] = field(default_factory=dict)
    instance: str = ""
    branch: str = ""
    pilot: bool = False
    software: str | None = None
    subdataset: str | None = None
    kept: list[tuple[str, str, bool]] = field(default_factory=list)  # (received, target, sensitive)
    dropped: list[str] = field(default_factory=list)
    commit: str | None = None  # the indexing commit; None when nothing was new
    pushed: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    triggered: list[str] = field(default_factory=list)
    undeclared: bool = False  # the instrument is not in the ma-DMP
    instrument: str = ""
    actions: list[str] = field(default_factory=list)

    @property
    def sample(self) -> str:
        return ",".join(f"{k}={v}" for k, v in self.entities.items())


def incoming_files(directory: Path) -> list[heur.IncomingFile]:
    if not directory.is_dir():
        raise IndexingError(f"{directory} is not a directory")
    found = sorted(p for p in directory.rglob("*") if p.is_file())
    if not found:
        raise IndexingError(f"{directory} holds no file")
    return [heur.IncomingFile(p, p.relative_to(directory).as_posix()) for p in found]


def instruments_at(stream, site: str) -> list[str]:
    return [i.instrument_id for i in stream.instruments if i.site == site and i.instrument_id]


def required_secrets(stream, site: sites.SiteConfig) -> list[str]:
    """Names of the secrets the site's storage for the stream's early stages needs."""
    names: set[str] = set()
    for dist in stream.distributions:
        host = dist.host
        if dist.stage not in remotes.EARLY_STAGES or host is None:
            continue
        names |= set(host.secrets.values())
        if host.site_dependent:
            names |= set(site.mapping(host.key).secrets.values())
    return sorted(names)


def check_credentials(stream, site: sites.SiteConfig, env: Mapping[str, str]) -> None:
    """Fail, naming them, when a secret is absent: before anything is cloned or changed."""
    try:
        missing = [n for n in required_secrets(stream, site) if not env.get(n)]
    except sites.SiteConfigError as exc:
        raise IndexingError(str(exc)) from exc
    if missing:
        raise IndexingError(
            "credential(s) not available in the environment: "
            + ", ".join(missing)
            + " (the site's storage needs them)"
        )


def _repo_name(stream: str, instance: str) -> str:
    return f"{stream}-{instance}"


def _git(ds: Dataset, *args: str) -> str:
    return ds.repo.call_git(list(args))


def _checkout(ds: Dataset, branch: str, origin: bool = True) -> None:
    repo = ds.repo
    heads = {r.split("/", 1)[1] for r in repo.get_remote_branches() if "/" in r}
    if origin and branch in heads:
        repo.call_git(["checkout", "-q", "-B", branch, f"origin/{branch}"])
    elif branch in repo.get_branches():
        repo.call_git(["checkout", "-q", branch])
    else:
        raise IndexingError(f"{ds.path}: no branch {branch!r} to index into")


def _clone(url: str, where: Path, branch: str) -> Dataset:
    ds = clone(source=url, path=str(where), result_renderer="disabled")
    _checkout(ds, branch)
    return ds


def _route(req: Request, stream, decision: heur.Decision) -> tuple[str, str, bool]:
    """The instrument, its instance and whether the ma-DMP declares it, from what the heuristic
    says (or the caller)."""
    instrument = req.instrument or decision.instrument
    if not instrument:
        raise IndexingError(
            "the instrument is not known: the heuristic names none and the site has several"
        )
    declared = {i.instrument_id: i for i in stream.instruments}
    if instrument in declared:
        where = declared[instrument].site
        if where != req.site.site:
            raise IndexingError(
                f"instrument {instrument!r} is declared at site {where!r}, not at {req.site.site!r}"
            )
        return instrument, plan.instance_name(req.site.site, instrument), True
    try:
        heur._safe_value("instrument", instrument)
    except heur.HeuristicError as exc:
        raise IndexingError(str(exc)) from exc
    return instrument, plan.instance_name(req.site.site, instrument), False


def _same(ds: Dataset, target: str, received: Path) -> bool:
    """Whether the dataset already holds exactly the received file at `target`."""
    path = Path(ds.path) / target
    if not (path.exists() or path.is_symlink()):
        return False
    key = subprocess.run(
        ["git", "annex", "lookupkey", target], cwd=ds.path, capture_output=True, text=True
    ).stdout.strip()
    if key:
        calc = subprocess.run(
            ["git", "annex", "calckey", str(received)], cwd=ds.path, capture_output=True, text=True
        ).stdout.strip()
        return calc == key
    staged = _git(ds, "ls-files", "-s", "--", target).split()
    blob = subprocess.run(
        ["git", "hash-object", str(received)], capture_output=True, text=True
    ).stdout.strip()
    return len(staged) > 1 and staged[1] == blob


def _record_message(decision: heur.Decision, instance: str, revision: str) -> str:
    sample = ",".join(f"{k}={v}" for k, v in decision.entities.items())
    lines = [
        f"Index sample {sample} from {instance}",
        "",
        f"faire-sample: {sample}",
        f"faire-pilot: {'true' if decision.pilot else 'false'}",
        f"faire-heuristic: {revision}",
        f"faire-instrument: {decision.instrument or instance}",
    ]
    if decision.software:
        lines.append(f"faire-software: {decision.software}")
    if decision.subdataset:
        lines.append(f"faire-subdataset: {decision.subdataset}")
    return "\n".join(lines)


def _mark(ds: Dataset, files: list[str], value: str) -> None:
    """Mark annexed files before any copy, so the wanted rules apply from the first transfer."""
    if not files:
        return
    unannexed = [f for f in files if not ds.repo.is_under_annex(f)]
    if unannexed:
        raise IndexingError(
            f"{', '.join(unannexed)} would be recorded in git history but is marked {value}: "
            "the dataset's .gitattributes must annex it"
        )
    subprocess.run(
        ["git", "annex", "metadata", "--set", f"{RESTRICTIONS}+={value}", "--", *files],
        cwd=ds.path,
        check=True,
        capture_output=True,
    )


def _heuristic_revision(ds: Dataset) -> str:
    """The revision of the heuristic in force: the last commit that touched its file."""
    out = _git(ds, "log", "-1", "--format=%H", "--", heur.HEURISTIC_FILE).strip()
    return out or ds.repo.get_hexsha()


def _fresh(ds: Dataset, decision: heur.Decision) -> list[heur.PlacedFile]:
    """The files of the sample the dataset does not hold yet."""
    return [p for p in decision.kept if not _same(ds, p.target, p.file.path)]


def _archive_enabled(ds: Dataset) -> bool:
    """Whether the dataset's own configuration asks for samples to be stored as archives."""
    path = Path(ds.path) / CONFIG
    return path.exists() and bool((yaml.safe_load(path.read_text()) or {}).get("archive"))


def _copy_in(ds: Dataset, fresh: list[heur.PlacedFile]) -> None:
    for placed in fresh:
        target = Path(ds.path) / placed.target
        if target.exists() or target.is_symlink():
            target.unlink()
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(placed.file.path, target)


def _pack(
    ds: Dataset, group: list[heur.PlacedFile], name: str, decision: heur.Decision, message: str
) -> str:
    """Store `group` as one archive and keep each member addressable by its path.

    The members are registered as parts of the archive (git-annex's `datalad-archives` remote
    fetches them from it) and dropped here, so only the archive travels to the storage.
    """
    slug = "_".join(f"{k}-{v}" for k, v in decision.entities.items())
    temporary = f"faire-archive-{slug}{name}.tar"  # visible: git-annex does not add dotfiles
    with tarfile.open(Path(ds.path) / temporary, "w") as archive:
        for placed in group:
            archive.add(placed.file.path, arcname=placed.target)
    subprocess.run(["git", "annex", "add", temporary], cwd=ds.path, check=True, capture_output=True)
    ds.save(path=temporary, message=message, result_renderer="disabled")
    with contextlib.chdir(ds.path):
        ds.add_archive_content(
            temporary,
            use_current_dir=True,
            drop_after=True,
            commit=False,
            allow_dirty=True,
            result_renderer="disabled",
            on_failure="stop",
        )
    kept = f"{ARCHIVES}/{slug}{name}.tar"
    (Path(ds.path) / ARCHIVES).mkdir(parents=True, exist_ok=True)
    ds.repo.call_git(["mv", temporary, kept])
    return kept


def _record(
    ds: Dataset, fresh: list[heur.PlacedFile], decision: heur.Decision, message: str
) -> str:
    """Copy the files in, save them with the record, and mark them before any transfer."""
    paths = [p.target for p in fresh]
    if _archive_enabled(ds):
        # sensitive files travel in an archive of their own, so storage rules can tell them apart
        archives = []
        for name, group in (
            ("", [p for p in fresh if not p.sensitive]),
            ("-sensitive", [p for p in fresh if p.sensitive]),
        ):
            if group:
                archives.append((_pack(ds, group, name, decision, message), name != ""))
        ds.save(message=message, result_renderer="disabled")
        commit = ds.repo.get_hexsha()
        _mark(ds, [p.target for p in fresh if p.sensitive], SENSITIVE)
        _mark(ds, [a for a, sensitive in archives if sensitive], SENSITIVE)
        if decision.pilot:
            _mark(ds, [*paths, *(a for a, _ in archives)], PILOT)
        return commit
    _copy_in(ds, fresh)
    ds.save(path=paths, message=message, result_renderer="disabled")
    commit = ds.repo.get_hexsha()
    _mark(ds, [p.target for p in fresh if p.sensitive], SENSITIVE)
    if decision.pilot:
        _mark(ds, paths, PILOT)
    return commit


def _use(action, ds: Dataset, spec: remotes.RemoteSpec) -> None:
    """Enable or create a remote; a storage that is not there stops the run before any change."""
    try:
        action(ds, spec)
    except remotes.RemoteError as exc:
        raise IndexingError(f"storage {spec.name!r} is unavailable: {exc}") from exc


def _transfer(ds: Dataset, specs: list[remotes.RemoteSpec], result: Result) -> None:
    """Content to the storage, before any history is pushed."""
    for spec in specs:
        try:
            ds.push(to=spec.name, result_renderer="disabled", on_failure="stop")
        except Exception as exc:
            raise IndexingError(f"cannot transfer the content to {spec.name!r}: {exc}") from exc
        result.pushed.append(spec.name)


def _push_history(ds: Dataset, label: str, result: Result) -> None:
    try:
        bootstrap.Bootstrap._push_state(ds)  # one retry when the git-annex branch moved meanwhile
    except Exception as exc:
        raise IndexingError(f"cannot push the history of {label}: {exc}") from exc
    result.pushed.append(label)


def downstream_of(dmp: Dmp, site: str, stream: str, instance: str, group: str) -> list[str]:
    """`group/name` of the datasets for which the instance is a triggering source."""
    key = f"{stream}/{instance}"
    return [
        f"{group}/{item.repo_name}"
        for item in plan.creation_plan(dmp, site)
        if any(link.key == key and link.triggering for link in item.sources)
    ]


def _create_instance(req: Request, instrument: str, base: Path, result: Result) -> None:
    platform, group = req.repositories.platform, req.repositories.group
    if platform is None:
        raise IndexingError("an instrument the ma-DMP does not declare needs a platform")
    try:
        name = undeclared.create_instance(
            req.dmp, req.site, platform, group, req.stream, instrument, base / "new-instance"
        )
    except undeclared.UndeclaredError as exc:
        raise IndexingError(str(exc)) from exc
    result.actions.append(f"created the instance {name} like the others of {req.stream}")


def _register(req: Request, result: Result, base: Path) -> list[str]:
    """Ask the derived datasets to register the new instance; return those that already have."""
    platform, group = req.repositories.platform, req.repositories.group
    repo_name = _repo_name(req.stream, result.instance)
    try:
        opened, registered = undeclared.propose_registrations(
            req.dmp,
            req.site,
            platform,
            group,
            req.stream,
            result.instrument,
            req.repositories.url(repo_name),
            base / "register",
        )
    except undeclared.UndeclaredError as exc:
        raise IndexingError(str(exc)) from exc
    for pr in opened:
        result.actions.append(
            f"registration pull request on {pr.repository}: {pr.url or pr.number}"
        )
    return registered


def _trigger(req: Request, result: Result, only: list[str] | None = None) -> None:
    """Start the derived datasets' pipelines for the pushed sample, as a merged pull request
    would. A lost trigger costs nothing: planning finds the sample from the state later."""
    platform, group = req.repositories.platform, req.repositories.group
    if platform is None or not req.trigger:
        result.actions.append("no platform to trigger the derived datasets on")
        return
    targets = downstream_of(
        undeclared.with_instrument(req.dmp, req.stream, result.instrument, req.site.site)
        if result.undeclared
        else req.dmp,
        req.site.site,
        req.stream,
        result.instance,
        group,
    )
    if only is not None:  # an undeclared instrument starts only what has registered it
        waiting = [t for t in targets if t not in only]
        if waiting:
            result.actions.append(
                f"not triggered, waiting for the registration: {', '.join(waiting)}"
            )
        targets = [t for t in targets if t in only]
    if not targets:
        return
    try:
        ids = triggering.trigger_downstream(
            platform,
            targets,
            req.stream,
            result.commit or "",
            result.sample,
            ref=PILOT_BRANCH if result.pilot else DEFAULT_BRANCH,
        )
    except Exception as exc:  # the history is pushed; only the notification is missing
        result.warnings.append(f"the derived datasets were not triggered: {exc}")
        return
    result.triggered = list(targets)
    result.actions.append(f"triggered {', '.join(targets)} ({len(ids)} pipeline(s))")


def index(req: Request) -> Result:
    """Record the received files as a sample; with `dry_run`, only report what would happen."""
    base = req.workdir or Path(tempfile.mkdtemp(prefix="faire-index-"))
    req.workdir = base
    result = _index(req)
    if req.dry_run:
        return result
    registered = _register(req, result, base) if result.undeclared else None
    if result.commit:
        _trigger(req, result, registered)
    return result


def _new_subdataset(
    work: Dataset, name: str, specs: list[remotes.RemoteSpec], heuristic: heur.Heuristic, ctx
) -> Dataset:
    """Create the subdataset, set it up before any file is recorded, and give it its remotes."""
    sub = work.create(path=name, result_renderer="disabled")
    if heuristic.has("setup"):
        try:
            heuristic.call("setup", sub, ctx)
        except heur.HeuristicError as exc:
            raise IndexingError(f"the setup of the subdataset {name!r} failed: {exc}") from exc
        sub.save(message=f"Set up {name} (heuristic setup)", result_renderer="disabled")
    else:  # the subdataset handles files as its parent does
        source = Path(work.path) / ".gitattributes"
        if source.exists():
            shutil.copy2(source, Path(sub.path) / ".gitattributes")
            sub.save(
                message="Take over the file handling of the instance", result_renderer="disabled"
            )
    bootstrap.Bootstrap._branches(sub)
    for spec in specs:
        _use(remotes.create, sub, spec)
    return sub


def _index_subdataset(
    req: Request,
    work: Dataset,
    decision: heur.Decision,
    result: Result,
    message: str,
    stream,
    repo_name: str,
    heuristic: heur.Heuristic,
    ctx: heur.Context,
) -> None:
    name = decision.subdataset
    assert name is not None
    sub_repo = f"{repo_name}-{remotes.slug(name)}"
    parent_specs = remotes.specs(stream, repo_name, req.site, stages=("collection",))
    specs = [s.for_repository(sub_repo) for s in parent_specs]
    known = {
        Path(s["path"]).relative_to(work.path).as_posix()
        for s in work.subdatasets(result_renderer="disabled", return_type="list")
    }
    if name in known:
        work.get(name, get_data=False, result_renderer="disabled")
        sub = Dataset(Path(work.path) / name)
        _checkout(sub, result.branch)
        for spec in specs:
            _use(remotes.enable, sub, spec)
        fresh = _fresh(sub, decision)
        if not fresh:
            result.actions.append(f"sample {result.sample} is already indexed in {name}")
            return
    else:
        sub = _new_subdataset(work, name, specs, heuristic, ctx)
        _checkout(sub, result.branch, origin=False)
        fresh = _fresh(sub, decision)
        result.actions.append(f"created the subdataset {name}")
    _record(sub, fresh, decision, message)
    result.actions.append(f"recorded {len(fresh)} file(s) in {name} on {result.branch}")
    _transfer(sub, specs, result)  # the content, then the subdataset's history, then the parent's
    url = req.repositories.ensure(sub_repo)
    if "origin" not in sub.repo.get_remotes():
        sub.siblings("add", name="origin", url=url, result_renderer="disabled")
    work.repo.call_git(["config", "-f", ".gitmodules", f"submodule.{name}.url", url])
    _push_history(sub, f"origin:{name}", result)
    work.save(path=[".gitmodules", name], message=message, result_renderer="disabled")
    result.commit = work.repo.get_hexsha()
    _push_history(work, "origin", result)


def _index(req: Request) -> Result:
    """Record the received files; the history is pushed when this returns."""
    dmp = req.dmp
    try:
        stream = dmp.dataset(req.stream)
    except KeyError:
        raise IndexingError(f"{req.stream!r} is not a dataset of the ma-DMP") from None
    if not stream.is_instrument_source:
        raise IndexingError(f"{req.stream!r} declares no instrument: it is not a source dataset")
    here = instruments_at(stream, req.site.site)
    if not here:
        raise IndexingError(f"{req.stream!r} has no instrument at site {req.site.site!r}")
    check_credentials(stream, req.site, os.environ if req.env is None else req.env)
    files = incoming_files(req.incoming)
    ctx = heur.Context(req.stream, req.site.site, tuple(dmp.sample_entities), tuple(here))

    base = req.workdir or Path(tempfile.mkdtemp(prefix="faire-index-"))
    probe_instance = plan.instance_name(req.site.site, req.instrument or here[0])
    probe_url = req.repositories.url(_repo_name(req.stream, probe_instance))
    probe = _clone(probe_url, base / "probe", DEFAULT_BRANCH)
    try:
        heuristic = heur.load(probe.path)
        decision = heur.decide(heuristic, files, ctx)
    except heur.HeuristicError as exc:
        raise IndexingError(str(exc)) from exc
    instrument, instance, declared = _route(req, stream, decision)

    result = Result(
        entities=decision.entities,
        instance=instance,
        branch=PILOT_BRANCH if decision.pilot else DEFAULT_BRANCH,
        pilot=decision.pilot,
        software=decision.software,
        subdataset=decision.subdataset,
        undeclared=not declared,
        instrument=instrument,
        kept=[(p.file.name, p.target, p.sensitive) for p in decision.kept],
        dropped=[f.name for f in decision.dropped],
    )
    where = f" in the subdataset {decision.subdataset}" if decision.subdataset else ""
    repo_name = _repo_name(req.stream, instance)
    if not declared:
        result.warnings.append(
            f"instrument {instrument!r} is not declared in the ma-DMP for {req.stream!r}: "
            f"its samples go to {instance} and trigger nothing until it is registered"
        )
    if req.dry_run:
        if not declared:
            result.actions.append(f"create the instance {instance} (not yet created)")
        result.actions.append(f"record the sample{where} in {instance} on {result.branch}")
        return result
    if not declared and not req.repositories.exists(repo_name):
        _create_instance(req, instrument, base, result)

    if instance == probe_instance and result.branch == DEFAULT_BRANCH:
        work = probe
    else:
        work = _clone(req.repositories.url(repo_name), base / "work", result.branch)
    message = _record_message(decision, instance, _heuristic_revision(work))
    specs = remotes.specs(stream, repo_name, req.site, stages=("collection",))
    for spec in specs:
        _use(remotes.enable, work, spec)

    if decision.subdataset is not None:
        _index_subdataset(req, work, decision, result, message, stream, repo_name, heuristic, ctx)
        return result
    fresh = _fresh(work, decision)
    if not fresh:
        result.actions.append(f"sample {result.sample} is already indexed in {instance}")
        return result
    result.commit = _record(work, fresh, decision, message)
    result.actions.append(f"recorded {len(fresh)} file(s) in {instance} on {result.branch}")
    _transfer(work, specs, result)
    _push_history(work, "origin", result)
    return result


def locator(platform: Platform | None, group: str | None, root: str | Path | None) -> Repositories:
    return Repositories(platform, group, root)


def report(result: Result, dry_run: bool = False) -> str:
    """What the heuristic decided and what was done (or would be)."""
    prefix = "would: " if dry_run else ""
    lines = [
        f"instance: {result.instance}",
        f"sample: {result.sample}",
        f"pilot: {'yes' if result.pilot else 'no'} (branch {result.branch})",
    ]
    if result.subdataset:
        lines.append(f"subdataset: {result.subdataset}")
    if result.software:
        lines.append(f"software: {result.software}")
    for received, target, sensitive in result.kept:
        lines.append(f"keep: {received} -> {target}{' [sensitive]' if sensitive else ''}")
    lines += [f"dropped: {name}" for name in result.dropped]
    lines += [prefix + action for action in result.actions]
    if result.commit:
        lines.append(f"commit: {result.commit}")
    return "\n".join(lines)
