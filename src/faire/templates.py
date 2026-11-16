"""Rendering dataset templates with copier into DataLad datasets."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import copier
from datalad.api import Dataset

ANSWERS_FILE = ".copier-answers.yml"


class TemplateError(RuntimeError):
    pass


def render(
    template: str,
    dataset: Dataset | str | Path,
    data: dict[str, Any],
    version: str | None = None,
) -> None:
    """Render `template` (at `version` when it is a git repository) into an existing dataset.

    The answers file written by copier records the template location, its version and the
    parameters, which is the dataset's record of what produced it.
    """
    root = Path(dataset.path if isinstance(dataset, Dataset) else dataset)
    try:
        copier.run_copy(
            template,
            root,
            data=data,
            vcs_ref=version,
            defaults=True,
            overwrite=True,
            quiet=True,
            answers_file=ANSWERS_FILE,
            cleanup_on_error=False,
        )
    except Exception as exc:  # copier raises many types for fetch/render failures
        raise TemplateError(f"cannot render template {template!r} at {version!r}: {exc}") from exc
