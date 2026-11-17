"""A small source dataset and a derived dataset with processing rules (DataLad API)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import yaml
from datalad.api import Dataset, containers_add, create

RULES = {
    "rules": [
        {
            "id": "process",
            "trigger": {"source": "src"},
            "container": "tool",
            "command": "sh -c 'mkdir -p {subject} && cat {inputs} > {outputs}'",
            "inputs": [{"pattern": "sourcedata/src/{subject}/*.txt", "required": True}],
            "outputs": ["{subject}/processed.txt"],
            "artifacts": [".faire/logs/"],
            "listing": ["{subject}/processed.txt"],
        }
    ],
    "checks": [
        {"id": "layout", "command": "test -f .faire/rules.yaml", "blocking": True},
        {"id": "extra", "command": "true", "blocking": False},
    ],
}


def write_source(path: Path, samples: dict[str, str], annex: bool = False) -> Dataset:
    """A source dataset; with `annex`, file content is annexed (absent from clones until got)."""
    src = create(str(path), cfg_proc=None if annex else "text2git", result_renderer="disabled")
    add_samples(src, samples)
    return src


def add_samples(src: Dataset, samples: dict[str, str]) -> None:
    for name, text in samples.items():
        target = Path(src.path) / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    src.save(message="add samples", result_renderer="disabled")


def make_derived(
    root: Path,
    source: Dataset | dict[str, Dataset],
    rules: dict | None = None,
    call_fmt: str = "{cmd}",
    annex: bool = False,
) -> Dataset:
    """A derived dataset on `dev` with the source installed under sourcedata/src."""
    ds = create(
        str(root / "derived"), cfg_proc=None if annex else "text2git", result_renderer="disabled"
    )
    image = root / "image.sif"
    image.write_bytes(b"image\n")
    containers_add(
        "tool", dataset=ds, url=str(image), call_fmt=call_fmt, result_renderer="disabled"
    )
    if isinstance(source, dict):  # a stream: one subdataset per instance
        for name, instance in source.items():
            ds.clone(
                source=instance.path, path=f"sourcedata/src/{name}", result_renderer="disabled"
            )
    else:
        ds.clone(source=source.path, path="sourcedata/src", result_renderer="disabled")
    (Path(ds.path) / ".faire").mkdir(exist_ok=True)
    (Path(ds.path) / ".faire/containers.yaml").write_text(
        yaml.safe_dump({"containers": [{"name": "tool", "url": str(image), "version": "test-1"}]})
    )
    (Path(ds.path) / ".faire/rules.yaml").write_text(yaml.safe_dump(rules or RULES))
    ds.save(message="rules", result_renderer="disabled")
    ds.repo.call_git(["branch", "-M", "dev"])
    return ds


def enable_directory_remote(ds: Dataset, name: str, directory: Path) -> None:
    """Enable a directory special remote in a clone.

    Recent git-annex asks for `verifyremote --safe N` before it uses a remote whose
    configuration came from the git-annex branch; older versions do not ask.
    """
    out = subprocess.run(
        ["git", "annex", "enableremote", name, f"directory={directory}"],
        cwd=ds.path,
        capture_output=True,
        text=True,
        check=True,
    )
    found = re.search(rf"verifyremote {re.escape(name)} --safe (\d+)", out.stdout + out.stderr)
    if found:
        subprocess.run(
            ["git", "annex", "verifyremote", name, "--safe", found.group(1)],
            cwd=ds.path,
            check=True,
            capture_output=True,
        )
