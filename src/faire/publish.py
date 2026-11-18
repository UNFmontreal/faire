"""Delivering a task's results: content to working storage, branch to the repository, pull request.

Order matters: a reviewer must be able to fetch every output as soon as the pull request exists,
so the content goes to the `review`-stage storage before the branch is pushed.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field

from datalad.api import Dataset

from faire import filters
from faire.platform import Platform, PullRequest, Repository

REVIEW_PREFIX = "review-"


@dataclass
class Published:
    pushed_to: list[str] = field(default_factory=list)
    pull_request: PullRequest | None = None
    notes: list[str] = field(default_factory=list)


def review_remotes(ds: Dataset) -> list[str]:
    """Special remotes bootstrap created for the dataset's `review` distributions."""
    names = (r.get("name") for r in ds.repo.get_special_remotes().values())
    return sorted(n for n in names if n and n.startswith(REVIEW_PREFIX))


def originals_of(ds: Dataset) -> list[tuple[str, str]]:
    """(key, path) of the originals inline processing replaced, in the commits not yet pushed."""
    body = ds.repo.call_git(["log", "HEAD", "--not", "--remotes", "--format=%B"])
    found: list[tuple[str, str]] = []
    for key, path in re.findall(r"^faire-original: (\S+) (.+)$", body, re.MULTILINE):
        if (key, path) not in found:
            found.append((key, path))
    return found


def _annex(ds: Dataset, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "annex", *args], cwd=ds.path, capture_output=True, text=True)


def copy_originals(ds: Dataset, remote: str, originals: list[tuple[str, str]]) -> None:
    """Send the replaced originals to the remote when its rules want them.

    They are no longer in the tree, so `copy --auto` cannot see them: the remote's wanted
    expression is evaluated here against each original's path and annex metadata.
    """
    wanted = _annex(ds, "wanted", remote).stdout.strip() or "anything"
    for key, path in originals:
        shown = _annex(ds, "metadata", "--json", "--key", key).stdout.strip()
        fields = (json.loads(shown).get("fields") or {}) if shown else {}
        metadata = {k: v for k, v in fields.items() if not k.endswith("-lastchanged")}
        if filters.matches(wanted, path, metadata):
            _annex(ds, "copy", "--to", remote, "--key", key)


def push_results(ds: Dataset, branch: str, remote: str = "origin") -> Published:
    """Send content to the review storage, then the branch (and annex metadata) to `remote`."""
    out = Published()
    keys = originals_of(ds)
    for name in review_remotes(ds):
        ds.push(to=name, result_renderer="disabled", on_failure="stop")
        # the replaced originals are no longer in the tree: copy them where they are wanted
        copy_originals(ds, name, keys)
        out.pushed_to.append(name)
    if not review_remotes(ds):
        out.notes.append("no review storage declared: content stays with the repository")
    if remote in {s["name"] for s in ds.siblings(result_renderer="disabled") if "name" in s}:
        ds.push(to=remote, since=None, result_renderer="disabled", on_failure="stop")
        out.pushed_to.append(remote)
    else:
        out.notes.append(f"no sibling {remote!r}: nothing pushed")
    return out


def description(
    platform: Platform,
    repo: Repository,
    branch: str,
    task_ids: list[str],
    listing: list[str],
) -> str:
    """Pull request text owned by the tool: what ran, and links to the files to review."""
    lines = ["Results of: " + ", ".join(f"`{t}`" for t in task_ids), ""]
    if listing:
        lines.append("Files to review:")
        lines += [f"- [{path}]({platform.file_url(repo, branch, path)})" for path in listing]
    return "\n".join(lines).rstrip() + "\n"


def open_pull_request(
    platform: Platform,
    repo: Repository,
    branch: str,
    target: str,
    title: str,
    task_ids: list[str],
    listing: list[str],
) -> PullRequest:
    return platform.ensure_pull_request(
        repo, branch, target, title, description(platform, repo, branch, task_ids, listing)
    )
