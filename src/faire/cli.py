"""Command-line entry point."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import click

from faire import (
    __version__,
    bootstrap,
    checks,
    ciplan,
    distribution,
    execute,
    federation,
    indexing,
    model,
    planning,
    publish,
    rules,
    sites,
    stages,
    undeclared,
)
from faire import (
    archive as archiving,
)
from faire import (
    release as releasing,
)
from faire import trigger as triggering
from faire import validate as validation
from faire.platform import PlatformError, credentials, factory
from faire.render import gitlab as gitlab_renderer


@click.group()
@click.version_option(__version__, prog_name="faire")
def main() -> None:
    """faire: manage research datasets from a machine-actionable DMP."""


@main.command()
@click.argument("madmp", type=click.Path(exists=True, dir_okay=False))
def validate(madmp: str) -> None:
    """Validate a ma-DMP against the RDA standard v1.3 and the faire profile."""
    try:
        with open(madmp) as handle:
            document = json.load(handle)
    except json.JSONDecodeError as exc:
        click.echo(f"{madmp}: not valid JSON: {exc}", err=True)
        sys.exit(1)
    violations = validation.validate(document)
    for violation in violations:
        click.echo(str(violation), err=True)
    if violations:
        click.echo(f"{len(violations)} violation(s) in {madmp}", err=True)
        sys.exit(1)
    click.echo(f"{madmp}: valid")


@main.command()
@click.argument("madmp", type=click.Path(exists=True, dir_okay=False))
@click.option("--site", required=True, help="Identifier of the site this runs for")
@click.option(
    "--sites-dir",
    type=click.Path(exists=True, file_okay=False),
    required=True,
    help="Directory of site configurations (<site>.yaml)",
)
@click.option("--root", type=click.Path(file_okay=False), required=True, help="Workspace directory")
@click.option("--study-template", required=True, help="Template of the study superdataset")
@click.option("--dry-run", is_flag=True, help="Report what would change and change nothing")
@click.option("--platform", "platform_name", type=click.Choice(["gitlab"]), default=None)
@click.option("--platform-url", envvar="FAIRE_PLATFORM_URL", default=None)
@click.option("--group", default=None, help="Platform group holding the study's repositories")
@click.option("--faire-image", default=None, help="Container image CI jobs run faire in")
def init(
    madmp,
    site,
    sites_dir,
    root,
    study_template,
    dry_run,
    platform_name,
    platform_url,
    group,
    faire_image,
):
    """Create or reconcile the study's datasets from the ma-DMP.

    Local-only unless --platform is given; the platform token is read from FAIRE_PLATFORM_TOKEN.
    """
    if platform_name and not (platform_url and group):
        click.echo("--platform needs --platform-url and --group", err=True)
        sys.exit(1)
    with open(madmp) as handle:
        document = json.load(handle)
    violations = validation.validate(document)
    if violations:
        for violation in violations:
            click.echo(str(violation), err=True)
        click.echo("ma-DMP is not valid, nothing created", err=True)
        sys.exit(1)
    try:
        config = sites.load(f"{sites_dir}/{site}.yaml")
        platform = factory.connect(platform_name, platform_url) if platform_name else None
        result = bootstrap.init(
            model.Dmp(document),
            config,
            bootstrap.Workspace(root),
            madmp,
            study_template,
            sites_dir=sites_dir,
            dry_run=dry_run,
            platform=platform,
            group=group,
            faire_image=faire_image,
        )
    except (sites.SiteConfigError, bootstrap.BootstrapError, PlatformError, OSError) as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)
    prefix = "would: " if dry_run else ""
    for action in result.actions:
        click.echo(prefix + action)
    for note in result.skipped:
        click.echo(f"skipped: {note}")
    if not result.actions:
        click.echo("no change")
    for note in result.notes:
        click.echo(f"note: {note}")
    for name, repos in sorted(result.missing_secrets.items()):
        click.echo(f"missing secret {name}: " + ", ".join(sorted(repos)))
    for difference in result.differences:
        click.echo(f"not applied: {difference}", err=True)
    if result.differences:
        sys.exit(1)


@main.command()
@click.argument("incoming", type=click.Path(exists=True, file_okay=False))
@click.option("--stream", required=True, help="Identifier of the instrument source dataset")
@click.option("--madmp", required=True, type=click.Path(exists=True, dir_okay=False))
@click.option("--site", required=True, help="Identifier of this site")
@click.option("--sites-dir", required=True, type=click.Path(exists=True, file_okay=False))
@click.option("--root", type=click.Path(file_okay=False), default=None, help="Local workspace")
@click.option("--platform", "platform_name", type=click.Choice(["gitlab"]), default=None)
@click.option("--platform-url", envvar="FAIRE_PLATFORM_URL", default=None)
@click.option("--group", default=None, help="Platform group holding the study's repositories")
@click.option("--instrument", default=None, help="Instrument, when the heuristic names none")
@click.option("--dry-run", is_flag=True, help="Report the heuristic's decisions, change nothing")
def index(
    incoming,
    stream,
    madmp,
    site,
    sites_dir,
    root,
    platform_name,
    platform_url,
    group,
    instrument,
    dry_run,
):
    """Record a directory of received files as a sample of an instrument's source dataset."""
    from contextlib import nullcontext

    document = json.load(open(madmp))
    violations = validation.validate(document)
    if violations:
        for violation in violations:
            click.echo(str(violation), err=True)
        click.echo("ma-DMP is not valid, nothing indexed", err=True)
        sys.exit(1)
    try:
        config = sites.load(f"{sites_dir}/{site}.yaml")
        platform = None
        if platform_name:
            if not (platform_url and group):
                raise indexing.IndexingError("--platform needs --platform-url and --group")
            platform = factory.connect(platform_name, platform_url)
        elif not root:
            raise indexing.IndexingError("give --root (a local workspace) or --platform")
        locate = indexing.locator(platform, group, root)
        request = indexing.Request(
            Path(incoming),
            stream,
            model.Dmp(document),
            config,
            locate,
            instrument=instrument,
            dry_run=dry_run,
        )
        with platform.git_auth() if platform else nullcontext():
            result = indexing.index(request)
    except (indexing.IndexingError, sites.SiteConfigError, PlatformError, OSError) as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)
    click.echo(indexing.report(result, dry_run))
    for warning in result.warnings:
        click.echo(f"warning: {warning}", err=True)


@main.group()
def ci() -> None:
    """Continuous-integration helpers."""


@ci.command("render")
@click.argument("plan", type=click.Path(exists=True, dir_okay=False))
@click.option("--platform", "platform_name", type=click.Choice(["gitlab"]), required=True)
@click.option(
    "--runner-tags",
    envvar="FAIRE_RUNNER_TAGS",
    default="{}",
    help='JSON mapping each site to its runner tags, e.g. {"a": ["site-a"]}',
)
def ci_render(plan: str, platform_name: str, runner_tags: str) -> None:
    """Render the pipeline definition for a plan produced by `faire plan --json`."""
    with open(plan) as handle:
        parsed = ciplan.CiPlan.from_json(handle.read())
    click.echo(gitlab_renderer.render_yaml(parsed, json.loads(runner_tags)), nl=False)


@main.command()
@click.option("--platform", "platform_name", default="gitlab", show_default=True)
@click.option("--platform-url", envvar="CI_SERVER_URL", required=True)
@click.option(
    "--downstream",
    envvar="FAIRE_DOWNSTREAM",
    required=True,
    help="Comma-separated group/name of the directly derived datasets",
)
@click.option("--upstream", envvar="FAIRE_DATASET", required=True, help="This dataset's id")
@click.option("--revision", envvar="CI_COMMIT_SHA", required=True, help="Revision that changed")
@click.option("--sample", default=None, help="Sample identifier, when one sample changed")
@click.option("--ref", default="dev", show_default=True)
def trigger(platform_name, platform_url, downstream, upstream, revision, sample, ref):
    """Start the planning pipelines of the datasets derived from this one."""
    try:
        platform = factory.connect(platform_name, platform_url)
        ids = triggering.trigger_downstream(
            platform, [d for d in downstream.split(",") if d], upstream, revision, sample, ref
        )
    except PlatformError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)
    for target, pipeline in zip(downstream.split(","), ids, strict=False):
        click.echo(f"{target}: pipeline {pipeline}")


DATASET = click.option(
    "--dataset",
    "root",
    type=click.Path(exists=True, file_okay=False),
    default=".",
    show_default=True,
)
UPDATE = click.option(
    "--update/--no-update",
    default=True,
    show_default=True,
    help="Bring the sources to their latest revision first",
)


def remotes_stages():
    from faire import remotes

    return remotes.ALL_STAGES


STREAMS = ("dev", "pilot")  # the branches samples are proposed to


def _load(root: str):
    from datalad.api import Dataset

    try:
        return Dataset(root), rules.load(root)
    except rules.RuleError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)


@main.command()
@DATASET
@UPDATE
@click.option(
    "--site",
    envvar="FAIRE_SITE",
    default="local",
    show_default=True,
    help="Site of samples whose origin the sources do not tell",
)
@click.option("--dataset-id", envvar="FAIRE_DATASET", required=True)
@click.option(
    "--madmp",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="ma-DMP, to place samples at the site of their instrument",
)
@click.option("--downstream", envvar="FAIRE_DOWNSTREAM", default="")
@click.option(
    "--since",
    envvar="CI_COMMIT_BEFORE_SHA",
    default=None,
    help="Previous tip of the branch: the merged pull requests since name the samples to trigger",
)
@click.option(
    "--reprocess",
    envvar="FAIRE_REPROCESS",
    default="",
    help="Samples (`entity=value,...`, separated by `;`) to run again although up to date",
)
@click.option("--json", "_json", is_flag=True, help="JSON output (the only format; the default)")
def plan(root, update, site, dataset_id, madmp, downstream, since, reprocess, _json):
    """Print the tasks due on the checked-out branch as JSON. Changes nothing but the sources."""
    ds, ruleset = _load(root)
    instances = planning.instances_from(model.load(madmp)) if madmp else None
    try:
        result = planning.make_plan(
            ds,
            ruleset,
            dataset_id=dataset_id,
            branch=planning.current_branch(ds),
            default_site=site,
            instances=instances,
            downstream=tuple(d for d in downstream.split(",") if d),
            update=update,
            since=since,
            reprocess=frozenset(x for x in reprocess.split(";") if x),
        )
    except (planning.PlanError, rules.RuleError) as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)
    click.echo(result.to_json(), nl=False)


@main.command()
@DATASET
@UPDATE
@click.option("--task", default=None, help="Identifier of one planned task")
@click.option("--all", "everything", is_flag=True, help="Run every due task, in order")
@click.option(
    "--base",
    default=None,
    help="Branch the sample branch starts from and its pull request targets; the checked-out "
    "`dev` or `pilot`, else `dev`",
)
@click.option("--site", envvar="FAIRE_SITE", default="local")
@click.option("--push/--no-push", default=True, show_default=True)
@click.option("--pull-request/--no-pull-request", default=True, show_default=True)
@click.option("--platform", "platform_name", default="gitlab", show_default=True)
@click.option("--platform-url", envvar="CI_SERVER_URL", default=None)
@click.option(
    "--project", envvar="CI_PROJECT_PATH", default=None, help="group/name of this dataset"
)
def run(
    root,
    update,
    task,
    everything,
    base,
    site,
    push,
    pull_request,
    platform_name,
    platform_url,
    project,
):
    """Run one planned task, or everything due, then push and open the pull request."""
    if bool(task) == everything:
        click.echo("give exactly one of --task and --all", err=True)
        sys.exit(2)
    ds, ruleset = _load(root)
    base = base or (
        planning.current_branch(ds) if planning.current_branch(ds) in STREAMS else "dev"
    )
    try:
        if everything:
            outcomes = execute.run_all(ds, ruleset, default_site=site, update=update, base=base)
        else:
            outcomes = [execute.run_task(ds, ruleset, task, update=update, base=base)]
    except (execute.RunError, rules.RuleError, planning.PlanError) as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)
    for outcome in outcomes:
        click.echo(outcome.message)
    done = [o for o in outcomes if o.status == "ran"]
    if not done or not push:
        return
    try:
        _deliver(ds, ruleset, done, base, pull_request, platform_name, platform_url, project)
    except Exception as exc:  # delivery problems are reported, the results stay committed
        click.echo(f"delivery failed: {exc}", err=True)
        sys.exit(1)


def _deliver(ds, ruleset, done, base, pull_request, platform_name, platform_url, project):
    by_branch: dict[str, list[execute.Outcome]] = {}
    for outcome in done:
        by_branch.setdefault(outcome.branch, []).append(outcome)
    start = ds.repo.get_active_branch()
    for branch, items in by_branch.items():
        if ds.repo.get_active_branch() != branch:
            ds.repo.call_git(["checkout", branch])
        with credentials.git_auth(platform_url, os.environ.get(factory.TOKEN_ENV)):
            result = publish.push_results(ds, branch)
        for note in result.notes:
            click.echo(note)
        if pull_request and platform_url and project:
            platform = factory.connect(platform_name, platform_url)
            group, _, name = project.rpartition("/")
            repo = platform.get_repository(group, name)
            listing = _listing(ruleset, items)
            pr = publish.open_pull_request(
                platform,
                repo,
                branch,
                base,
                f"{branch}: " + ", ".join(i.task for i in items),
                [i.task for i in items],
                listing,
            )
            click.echo(f"pull request {pr.url or pr.number}")
    if start and ds.repo.get_active_branch() != start:
        ds.repo.call_git(["checkout", start])


def _listing(ruleset, items) -> list[str]:
    paths: list[str] = []
    for item in items:
        rule_id, sample = planning.parse_task_id(item.task)
        for pattern in ruleset.rule(rule_id).listing:
            for output in item.output_samples or [{}]:
                path = rules.resolve(pattern, {**sample, **output})
                if path not in paths:
                    paths.append(path)
    return paths


@main.command("test")
@DATASET
@click.option("--list", "listing", is_flag=True, help="List the checks of the checked-out branch")
@click.option("--check", default=None, help="Run one check")
def test_command(root, listing, check):
    """Run the applicable checks (or one), or list them.

    Without options, runs every check that applies to the checked-out branch, in order, and exits
    non-zero when a blocking check fails; an advisory check that fails is only reported.
    """
    ds, ruleset = _load(root)
    if listing and check:
        click.echo("give at most one of --list and --check", err=True)
        sys.exit(2)
    branch = planning.current_branch(ds)
    if listing:
        click.echo(
            json.dumps(
                [{"id": c.id, "blocking": c.blocking} for c in checks.applicable(ruleset, branch)]
            )
        )
        return
    wanted = [check] if check else [c.id for c in checks.applicable(ruleset, branch)]
    failed = False
    for check_id in wanted:
        try:
            result = checks.run_check(ds, ruleset, check_id)
        except rules.RuleError as exc:
            click.echo(str(exc), err=True)
            sys.exit(1)
        click.echo(result.output, nl=False)
        click.echo(
            f"{result.check}: {'passed' if result.ok else 'failed'}"
            f"{'' if result.blocking else ' (advisory)'}",
            err=not result.ok,
        )
        failed = failed or (not result.ok and result.blocking)
    if failed:
        sys.exit(1)


@main.command()
@DATASET
@click.option("--platform", "platform_name", default="gitlab", show_default=True)
@click.option("--platform-url", envvar="CI_SERVER_URL", required=True)
@click.option(
    "--group",
    envvar="CI_PROJECT_NAMESPACE",
    required=True,
    help="Platform group holding the study's repositories",
)
def registrations(root, platform_name, platform_url, group):
    """Propose to the study the instruments registered as sources here that its ma-DMP lacks.

    Meant for the pipeline of `dev`: once a registration of an instrument instance is merged,
    this opens the pull request adding the instrument to the ma-DMP. Changes nothing otherwise.
    """
    from datalad.api import Dataset

    ds = Dataset(root)
    if planning.current_branch(ds) != "dev":
        click.echo("not on dev: nothing to propose")
        return
    try:
        platform = factory.connect(platform_name, platform_url)
        with platform.git_auth():
            opened = undeclared.propose_instruments(ds, platform, group)
    except (undeclared.UndeclaredError, PlatformError) as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)
    for pr in opened:
        click.echo(f"pull request on the study: {pr.url or pr.number}")
    if not opened:
        click.echo("every registered instrument is in the ma-DMP")


@main.command()
@DATASET
@click.option("--target", default="dev", show_default=True, help="Branch to propose the sample to")
@click.option("--platform", "platform_name", default="gitlab", show_default=True)
@click.option("--platform-url", envvar="CI_SERVER_URL", required=True)
@click.option(
    "--project", envvar="CI_PROJECT_PATH", required=True, help="group/name of this dataset"
)
def propose(root, target, platform_name, platform_url, project):
    """Open (or update) the pull request of a sample branch pushed by hand.

    The branch is named `feature/<entity>-<value>_...`; the pull request names the sample.
    Does nothing on any other branch.
    """
    from datalad.api import Dataset

    ds = Dataset(root)
    branch = planning.current_branch(ds)
    try:
        names = rules.entity_names(root)
    except rules.RuleError:
        names = None
    sample = planning.sample_of_branch(branch, names)
    if sample is None:
        click.echo(f"{branch or 'HEAD'} is not a sample branch: no pull request")
        return
    key = ",".join(f"{k}={v}" for k, v in sample.items())
    try:
        platform = factory.connect(platform_name, platform_url)
        group, _, name = project.rpartition("/")
        repo = platform.get_repository(group, name)
        if repo is None:
            raise PlatformError(f"{project}: no such repository on the platform")
        pr = platform.ensure_pull_request(
            repo,
            branch,
            target,
            f"Sample {key}",
            f"Contribution of the sample `{key}` (branch `{branch}`), proposed to `{target}`.\n",
        )
    except PlatformError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)
    click.echo(f"pull request for sample {key}: {pr.url or pr.number}")


@main.command()
@click.argument("samples", nargs=-1, required=True)
@click.option("--dataset-id", envvar="FAIRE_DATASET", required=True)
@click.option("--platform", "platform_name", default="gitlab", show_default=True)
@click.option("--platform-url", envvar="CI_SERVER_URL", required=True)
@click.option(
    "--project", envvar="CI_PROJECT_PATH", required=True, help="group/name of the dataset"
)
@click.option("--ref", default="dev", show_default=True, help="`dev`, or `pilot` for pilot samples")
def reprocess(samples, dataset_id, platform_name, platform_url, project, ref):
    """Start the pipeline of a dataset for named samples, as an upstream merge would.

    Each sample is given as `entity=value,...`. The pipeline plans those samples although their
    results are up to date, and each ends in a pull request; use it after fixing the processing.
    """
    try:
        platform = factory.connect(platform_name, platform_url)
        triggering.trigger_downstream(
            platform,
            [project],
            dataset_id,
            "",
            ref=ref,
            extra={"FAIRE_REPROCESS": ";".join(samples)},
        )
    except PlatformError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)
    click.echo(f"reprocessing {len(samples)} sample(s) in {project}")


@main.command()
@DATASET
@UPDATE
@click.argument("samples", nargs=-1)
@click.option("--platform", "platform_name", default="gitlab", show_default=True)
@click.option("--platform-url", envvar="CI_SERVER_URL", default=None)
@click.option("--project", envvar="CI_PROJECT_PATH", default=None, help="group/name of the dataset")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output")
def stage(root, update, samples, platform_name, platform_url, project, as_json):
    """Report the lifecycle stage of the dataset's samples (all of them, or those named).

    With the platform given, only samples whose pull request is open count as under review.
    """
    from datalad.api import Dataset

    ds = Dataset(root)
    open_branches = None
    if platform_url and project:
        try:
            platform = factory.connect(platform_name, platform_url)
            group, _, name = project.rpartition("/")
            repo = platform.get_repository(group, name)
            if repo is not None:
                open_branches = {pr.source for pr in platform.open_pull_requests(repo)}
        except PlatformError as exc:
            click.echo(str(exc), err=True)
            sys.exit(1)
    found = stages.sample_stages(ds, open_branches, stages.source_samples(ds, update))
    if samples:
        missing = [s for s in samples if s not in found]
        if missing:
            click.echo("unknown sample(s): " + ", ".join(missing), err=True)
            sys.exit(1)
        found = {k: v for k, v in found.items() if k in samples}
    if as_json:
        click.echo(json.dumps(found, indent=2))
        return
    for key, value in found.items():
        click.echo(f"{key}: {value}")


@main.command()
@click.argument("tag")
@click.option("--site", envvar="FAIRE_SITE", required=True, help="Identifier of this site")
@click.option("--platform", "platform_name", default="gitlab", show_default=True)
@click.option("--platform-url", envvar="CI_SERVER_URL", required=True)
@click.option(
    "--group", envvar="CI_PROJECT_NAMESPACE", required=True, help="Group holding the study"
)
def release(tag, site, platform_name, platform_url, group):
    """Release the whole study as TAG: every dataset's `dev` to `main`, tagged together.

    Refused, with nothing tagged, when a derived dataset is behind its sources.
    """
    try:
        platform = factory.connect(platform_name, platform_url)
        with platform.git_auth():
            report = releasing.release(platform, group, tag, site)
    except (releasing.ReleaseError, PlatformError) as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)
    for line in report.lines():
        click.echo(line, err=report.refused)
    if report.refused:
        sys.exit(1)


@main.command()
@DATASET
@click.option("--stage", required=True, type=click.Choice(list(remotes_stages())))
@click.option("--distribution", "named", multiple=True, help="Fulfil only this distribution")
@click.option("--madmp", envvar="FAIRE_MADMP", required=True, type=click.Path(exists=True))
@click.option("--site", envvar="FAIRE_SITE", required=True, help="Identifier of this site")
@click.option("--sites-dir", envvar="FAIRE_SITES_DIR", required=True, type=click.Path(exists=True))
@click.option("--tag", help="The release being fulfilled: its record is written to the ma-DMP")
@click.option(
    "--study",
    type=click.Path(exists=True),
    help="Clone of the study superdataset to write the established facts to",
)
@click.option(
    "--workspace",
    type=click.Path(exists=True, file_okay=False),
    help="Exchange every federated dataset of this workspace with the hub, sources first",
)
def sync(root, stage, named, madmp, site, sites_dir, tag, study, workspace):
    """Fulfil the distributions of this dataset bound to a stage.

    One-way distributions get the dataset's content (through git-annex where the host is a
    git-annex remote, so that the location is recorded) and the location is shared; a failing
    distribution is reported by name and the others are still attempted.
    """
    import yaml
    from datalad.api import Dataset

    ds = Dataset(root)
    try:
        dmp = model.load(madmp)
        config = sites.load(f"{sites_dir}/{site}.yaml")
        if workspace:
            exchanged = federation.sync_all(Path(workspace), dmp, config)
            for done in exchanged:
                click.echo(done.describe(), err=not done.ok)
            sys.exit(0 if all(x.ok for x in exchanged) else 1)
        record = yaml.safe_load((Path(root) / bootstrap.RECORD).read_text())
        dataset = dmp.dataset(record["dataset_id"])
        repo_name = (
            f"{record['stream']}-{record['instance']}"
            if record.get("instance")
            else (record["dataset_id"])
        )
    except (OSError, KeyError, sites.SiteConfigError) as exc:
        click.echo(f"cannot read the study's description: {exc}", err=True)
        sys.exit(1)
    outcomes = distribution.fulfil(ds, dataset, repo_name, config, stage, list(named) or None)
    hub = dataset.hub_distribution
    exchanging = hub is not None and hub.stage == stage and not (named and hub.title not in named)
    if exchanging:
        done = federation.exchange(ds, config, repo_name, None, dataset)
        click.echo(done.describe(), err=not done.ok)
        if not done.ok:
            sys.exit(1)
    if not outcomes and not exchanging:
        click.echo(f"no distribution of {record['dataset_id']} is bound to {stage}")
    for outcome in outcomes:
        where = f" ({outcome.remote})" if outcome.remote else ""
        detail = f": {outcome.message}" if outcome.message else ""
        made = ", remote created" if outcome.created else ""
        click.echo(
            f"{outcome.distribution}{where}: {outcome.status}, "
            f"{outcome.transferred} file(s) transferred{made}{detail}",
            err=not outcome.ok,
        )
    if outcomes and study and stage in ("release", "archival"):
        try:
            for line in distribution.complete(ds, dataset, stage, outcomes, Dataset(study), tag):
                click.echo(line)
        except distribution.FulfilmentError as exc:
            click.echo(str(exc), err=True)
            sys.exit(1)
    if not all(o.ok for o in outcomes):
        sys.exit(1)


@main.command()
@click.option("--root", required=True, type=click.Path(exists=True, file_okay=False))
@click.option("--madmp", envvar="FAIRE_MADMP", required=True, type=click.Path(exists=True))
@click.option("--site", envvar="FAIRE_SITE", required=True, help="Identifier of this site")
@click.option("--sites-dir", envvar="FAIRE_SITES_DIR", required=True, type=click.Path(exists=True))
def archive(root, madmp, site, sites_dir):
    """Archive the whole study: history and the content of every release, platform-free.

    Run from the workspace holding the study's repositories, after the releases to keep.
    """
    try:
        report = archiving.archive(
            Path(root), model.load(madmp), sites.load(f"{sites_dir}/{site}.yaml")
        )
    except (archiving.ArchiveError, sites.SiteConfigError, OSError) as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)
    for outcome in report.content:
        click.echo(f"{outcome.distribution}: {outcome.status}", err=not outcome.ok)
    click.echo(f"archived {', '.join(report.archived)} ({len(report.tags)} release(s))")
    if not report.ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
