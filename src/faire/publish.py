"""Delivering a task's results: content to working storage, branch to the repository, pull request.

Order matters: a reviewer must be able to fetch every output as soon as the pull request exists,
so the content goes to the `review`-stage storage before the branch is pushed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from datalad.api import Dataset

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


def push_results(ds: Dataset, branch: str, remote: str = "origin") -> Published:
    """Send content to the review storage, then the branch (and annex metadata) to `remote`."""
    out = Published()
    for name in review_remotes(ds):
        ds.push(to=name, result_renderer="disabled", on_failure="stop")
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
