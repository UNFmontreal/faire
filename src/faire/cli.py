"""Command-line entry point."""

from __future__ import annotations

import json
import sys

import click

from faire import __version__, bootstrap, model, sites
from faire import validate as validation


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
def init(madmp, site, sites_dir, root, study_template, dry_run):
    """Create or reconcile the study's datasets from the ma-DMP (local-only mode)."""
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
        result = bootstrap.init(
            model.Dmp(document),
            config,
            bootstrap.Workspace(root),
            madmp,
            study_template,
            sites_dir=sites_dir,
            dry_run=dry_run,
        )
    except (sites.SiteConfigError, bootstrap.BootstrapError, OSError) as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)
    prefix = "would: " if dry_run else ""
    for action in result.actions:
        click.echo(prefix + action)
    for note in result.skipped:
        click.echo(f"skipped: {note}")
    if not result.actions:
        click.echo("no change")
    for difference in result.differences:
        click.echo(f"not applied: {difference}", err=True)
    if result.differences:
        sys.exit(1)


if __name__ == "__main__":
    main()
