"""Command-line entry point."""

from __future__ import annotations

import json
import os
import sys

import click

from faire import (
    __version__,
    bootstrap,
    checks,
    ciplan,
    execute,
    model,
    planning,
    publish,
    rules,
    sites,
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
def plan(root, update, site, dataset_id, madmp, downstream):
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
@click.option("--base", default="dev", show_default=True)
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
            path = rules.resolve(pattern, sample)
            if path not in paths:
                paths.append(path)
    return paths


@main.command("test")
@DATASET
@click.option("--list", "listing", is_flag=True, help="List the checks of the checked-out branch")
@click.option("--check", default=None, help="Run one check")
def test_command(root, listing, check):
    """List the dataset's checks, or run one of them."""
    ds, ruleset = _load(root)
    if listing == bool(check):
        click.echo("give exactly one of --list and --check", err=True)
        sys.exit(2)
    if listing:
        branch = planning.current_branch(ds)
        click.echo(
            json.dumps(
                [{"id": c.id, "blocking": c.blocking} for c in checks.applicable(ruleset, branch)]
            )
        )
        return
    try:
        result = checks.run_check(ds, ruleset, check)
    except rules.RuleError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)
    click.echo(result.output, nl=False)
    click.echo(
        f"{result.check}: {'passed' if result.ok else 'failed'}"
        f"{'' if result.blocking else ' (advisory)'}",
        err=not result.ok,
    )
    if not result.ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
