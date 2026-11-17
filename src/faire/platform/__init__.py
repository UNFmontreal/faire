"""Platform interface: everything faire asks of a DevOps platform, and nothing else.

Behaviour specified for bootstrap, lifecycle and distribution is expressed with these
operations only, so supporting another platform means implementing this class.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

OPERATIONS = (
    "ensure_group",
    "ensure_repository",
    "protect_branch",
    "protect_tag",
    "set_variable",
    "ensure_pull_request",
    "trigger_pipeline",
)

AUTOMATION, MAINTAINERS = "automation", "maintainers"


class PlatformError(RuntimeError):
    pass


class UnsupportedOperation(PlatformError):
    def __init__(self, operations: list[str], platform: str):
        self.operations = operations
        super().__init__(f"platform {platform!r} does not support: " + ", ".join(operations))


@dataclass(frozen=True)
class Group:
    path: str  # full path, `parent/child` for nested groupings


@dataclass(frozen=True)
class Repository:
    group: str
    name: str
    url: str  # where git can clone and push

    @property
    def path(self) -> str:
        return f"{self.group}/{self.name}"


@dataclass(frozen=True)
class PullRequest:
    repository: str  # Repository.path
    number: int
    source: str
    target: str
    title: str
    description: str
    url: str = ""


@dataclass(frozen=True)
class Protection:
    """Result of protecting a branch: what the platform could actually enforce."""

    pattern: str
    approvals_enforced: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)


class Platform(ABC):
    name = "platform"
    #: operations this platform implements; commands check them before changing anything
    supported: frozenset[str] = frozenset(OPERATIONS)

    def require(self, operations: list[str] | tuple[str, ...]) -> None:
        missing = [op for op in operations if op not in self.supported]
        if missing:
            raise UnsupportedOperation(missing, self.name)

    @abstractmethod
    def ensure_group(self, path: str) -> Group:
        """Create the (possibly nested) grouping if missing; return it."""

    @abstractmethod
    def ensure_repository(self, group: str, name: str) -> Repository:
        """Create an empty repository in the group if missing; look it up otherwise."""

    @abstractmethod
    def get_repository(self, group: str, name: str) -> Repository | None: ...

    @abstractmethod
    def protect_branch(self, repo: Repository, pattern: str, approvals: int = 0) -> Protection:
        """Accept changes to branches matching `pattern` only through merged pull requests
        or the automation identity, with `approvals` human approvals when the platform can
        require them."""

    @abstractmethod
    def protect_tag(self, repo: Repository, pattern: str) -> None:
        """Allow creating matching tags only to maintainers or the automation identity."""

    @abstractmethod
    def set_variable(
        self,
        repo: Repository,
        key: str,
        value: str,
        protected_refs_only: bool = False,
    ) -> None:
        """Set a CI variable (create or update). `protected_refs_only` limits it to
        protected branches and tags."""

    @abstractmethod
    def get_variables(self, repo: Repository) -> dict[str, str]: ...

    @abstractmethod
    def defined_variables(self, repo: Repository) -> set[str]:
        """Names of every variable visible to the repository's pipelines, including those
        defined on its groupings. Used to report secrets operators still have to provide."""

    @abstractmethod
    def ensure_pull_request(
        self, repo: Repository, source: str, target: str, title: str, description: str
    ) -> PullRequest:
        """Open a pull request, or update the open one for the same branches."""

    @abstractmethod
    def file_url(self, repo: Repository, ref: str, path: str) -> str:
        """Link through which a reviewer opens a file of a branch."""

    @abstractmethod
    def trigger_pipeline(self, repo: Repository, ref: str, variables: dict[str, str]) -> str:
        """Start a pipeline in another repository; return its identifier."""
