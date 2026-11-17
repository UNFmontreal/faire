"""In-memory platform for tests. Repositories are real bare git repositories on disk."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from datalad.support.gitrepo import GitRepo

from faire.platform import (
    Group,
    Platform,
    PlatformError,
    Protection,
    PullRequest,
    Repository,
)


@dataclass
class _Repo:
    repo: Repository
    branch_patterns: dict[str, int] = field(default_factory=dict)  # pattern -> approvals
    tag_patterns: set[str] = field(default_factory=set)
    variables: dict[str, tuple[str, bool]] = field(default_factory=dict)
    pull_requests: list[PullRequest] = field(default_factory=list)


class FakePlatform(Platform):
    name = "fake"

    def __init__(self, root: str | Path, supports_approvals: bool = True):
        self.root = Path(root)
        self.supports_approvals = supports_approvals
        self.groups: set[str] = set()
        self.repos: dict[str, _Repo] = {}
        self.pipelines: list[tuple[str, str, dict[str, str]]] = []
        self.group_variables: dict[str, dict[str, str]] = {}

    def ensure_group(self, path: str) -> Group:
        parts = path.strip("/").split("/")
        for i in range(1, len(parts) + 1):
            self.groups.add("/".join(parts[:i]))
        return Group(path.strip("/"))

    def get_repository(self, group: str, name: str) -> Repository | None:
        entry = self.repos.get(f"{group}/{name}")
        return entry.repo if entry else None

    def ensure_repository(self, group: str, name: str) -> Repository:
        existing = self.get_repository(group, name)
        if existing:
            return existing
        if group not in self.groups:
            raise PlatformError(f"group {group!r} does not exist")
        path = self.root / group / f"{name}.git"
        path.parent.mkdir(parents=True, exist_ok=True)
        GitRepo(str(path), create=True, bare=True)
        repo = Repository(group, name, str(path))
        self.repos[repo.path] = _Repo(repo)
        return repo

    def _entry(self, repo: Repository) -> _Repo:
        try:
            return self.repos[repo.path]
        except KeyError:
            raise PlatformError(f"unknown repository {repo.path!r}") from None

    def protect_branch(self, repo: Repository, pattern: str, approvals: int = 0) -> Protection:
        enforced = approvals > 0 and self.supports_approvals
        self._entry(repo).branch_patterns[pattern] = approvals if enforced else 0
        notes = ()
        if approvals and not enforced:
            notes = ("approvals cannot be required; merges restricted to maintainers",)
        return Protection(pattern, enforced, notes)

    def protect_tag(self, repo: Repository, pattern: str) -> None:
        self._entry(repo).tag_patterns.add(pattern)

    def set_variable(
        self, repo: Repository, key: str, value: str, protected_refs_only: bool = False
    ) -> None:
        self._entry(repo).variables[key] = (value, protected_refs_only)

    def get_variables(self, repo: Repository) -> dict[str, str]:
        return {k: v for k, (v, _) in self._entry(repo).variables.items()}

    def defined_variables(self, repo: Repository) -> set[str]:
        names = set(self._entry(repo).variables)
        parts = repo.group.split("/")
        for i in range(1, len(parts) + 1):
            names |= set(self.group_variables.get("/".join(parts[:i]), {}))
        return names

    def ensure_pull_request(
        self, repo: Repository, source: str, target: str, title: str, description: str
    ) -> PullRequest:
        entry = self._entry(repo)
        for i, pr in enumerate(entry.pull_requests):
            if (pr.source, pr.target) == (source, target):
                entry.pull_requests[i] = PullRequest(
                    repo.path, pr.number, source, target, title, description, pr.url
                )
                return entry.pull_requests[i]
        number = len(entry.pull_requests) + 1
        pr = PullRequest(
            repo.path, number, source, target, title, description, f"fake://{repo.path}/{number}"
        )
        entry.pull_requests.append(pr)
        return pr

    def file_url(self, repo: Repository, ref: str, path: str) -> str:
        return f"fake://{repo.path}/blob/{ref}/{path}"

    def list_pull_requests(self, repo: Repository) -> list[PullRequest]:
        return list(self._entry(repo).pull_requests)

    def trigger_pipeline(self, repo: Repository, ref: str, variables: dict[str, str]) -> str:
        self._entry(repo)
        self.pipelines.append((repo.path, ref, dict(variables)))
        return str(len(self.pipelines))

    # helpers for tests
    def set_group_variable(self, group: str, key: str, value: str) -> None:
        self.group_variables.setdefault(group, {})[key] = value

    def protected_branches(self, repo: Repository) -> dict[str, int]:
        return dict(self._entry(repo).branch_patterns)

    def protected_tags(self, repo: Repository) -> set[str]:
        return set(self._entry(repo).tag_patterns)
