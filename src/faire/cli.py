"""Command-line entry point."""

from __future__ import annotations

import json
import sys

import click

from faire import __version__
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


if __name__ == "__main__":
    main()
