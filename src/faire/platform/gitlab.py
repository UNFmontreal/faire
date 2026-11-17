"""GitLab backend, on python-gitlab."""

from __future__ import annotations

import time
from typing import Any

import gitlab
from gitlab import exceptions as gle

from faire.platform import (
    Group,
    Platform,
    PlatformError,
    Protection,
    PullRequest,
    Repository,
    credentials,
)

MAINTAINER = 40  # GitLab access level: Maintainer
APPROVAL_RULE = "faire: human approval"


class GitLabPlatform(Platform):
    name = "gitlab"

    def __init__(self, url: str, token: str, session: Any = None):
        self.url, self._token = url, token
        self.gl = gitlab.Gitlab(url, private_token=token, session=session)

    def git_auth(self):
        return credentials.git_auth(self.url, self._token)

    def _wrap(self, exc: Exception) -> PlatformError:
        return PlatformError(f"GitLab: {exc}")

    # -- grouping and repositories ------------------------------------------------------------

    def _group(self, path: str) -> Any:
        try:
            return self.gl.groups.get(path)
        except gle.GitlabGetError as exc:
            if exc.response_code == 404:
                return None
            raise self._wrap(exc) from exc

    def ensure_group(self, path: str) -> Group:
        parts = path.strip("/").split("/")
        parent = None
        for i, part in enumerate(parts):
            prefix = "/".join(parts[: i + 1])
            group = self._group(prefix)
            if group is None:
                payload: dict[str, Any] = {"name": part, "path": part}
                if parent is not None:
                    payload["parent_id"] = parent.id
                try:
                    group = self.gl.groups.create(payload)
                except gle.GitlabError as exc:
                    raise self._wrap(exc) from exc
            parent = group
        return Group("/".join(parts))

    def _project(self, group: str, name: str) -> Any:
        try:
            return self.gl.projects.get(f"{group}/{name}")
        except gle.GitlabGetError as exc:
            if exc.response_code == 404:
                return None
            raise self._wrap(exc) from exc

    def get_repository(self, group: str, name: str) -> Repository | None:
        project = self._project(group, name)
        return self._repo(group, name, project) if project else None

    @staticmethod
    def _repo(group: str, name: str, project: Any) -> Repository:
        return Repository(group, name, project.http_url_to_repo)

    def ensure_repository(self, group: str, name: str) -> Repository:
        project = self._project(group, name)
        if project is None:
            parent = self._group(group)
            if parent is None:
                raise PlatformError(f"group {group!r} does not exist")
            try:
                project = self.gl.projects.create(
                    {"name": name, "path": name, "namespace_id": parent.id}
                )
            except gle.GitlabError as exc:
                raise self._wrap(exc) from exc
        return self._repo(group, name, project)

    def _p(self, repo: Repository) -> Any:
        project = self._project(repo.group, repo.name)
        if project is None:
            raise PlatformError(f"unknown repository {repo.path!r}")
        return project

    # -- protection -----------------------------------------------------------------------------

    @staticmethod
    def _replace(collection: Any, name: str, payload: dict[str, Any]) -> None:
        """Create a protection, replacing one that exists. GitLab protects a repository's first
        pushed branch moments after the push, so a conflict is resolved by replacing it."""
        for attempt in range(5):
            try:
                collection.create(payload)
                return
            except gle.GitlabCreateError as exc:
                taken = exc.response_code == 409 or "already" in str(exc.error_message)
                if not taken or attempt == 4:
                    raise
            try:
                collection.get(name).delete()
            except gle.GitlabGetError:
                time.sleep(1)  # not visible yet: try again

    def protect_branch(self, repo: Repository, pattern: str, approvals: int = 0) -> Protection:
        project = self._p(repo)
        try:
            self._replace(
                project.protectedbranches,
                pattern,
                {
                    "name": pattern,
                    "push_access_level": MAINTAINER,
                    "merge_access_level": MAINTAINER,
                    "allow_force_push": False,
                },
            )
        except gle.GitlabError as exc:
            raise self._wrap(exc) from exc
        if not approvals:
            return Protection(pattern)
        try:
            names = {r.name for r in project.approvalrules.list(get_all=True)}
            if APPROVAL_RULE not in names:
                project.approvalrules.create(
                    {"name": APPROVAL_RULE, "approvals_required": approvals}
                )
            return Protection(pattern, approvals_enforced=True)
        except gle.GitlabError:
            return Protection(
                pattern,
                False,
                (
                    "approval rules are not available on this GitLab plan; merges are "
                    "restricted to maintainers, who approve by merging",
                ),
            )

    def protect_tag(self, repo: Repository, pattern: str) -> None:
        project = self._p(repo)
        try:
            self._replace(
                project.protectedtags,
                pattern,
                {"name": pattern, "create_access_level": MAINTAINER},
            )
        except gle.GitlabError as exc:
            raise self._wrap(exc) from exc

    # -- variables -------------------------------------------------------------------------------

    def set_variable(
        self, repo: Repository, key: str, value: str, protected_refs_only: bool = False
    ) -> None:
        project = self._p(repo)
        try:
            try:
                var = project.variables.get(key)
                var.value = value
                var.protected = protected_refs_only
                var.save()
            except gle.GitlabGetError:
                project.variables.create(
                    {"key": key, "value": value, "protected": protected_refs_only}
                )
        except gle.GitlabError as exc:
            raise self._wrap(exc) from exc

    def get_variables(self, repo: Repository) -> dict[str, str]:
        try:
            return {v.key: v.value for v in self._p(repo).variables.list(get_all=True)}
        except gle.GitlabError as exc:
            raise self._wrap(exc) from exc

    def defined_variables(self, repo: Repository) -> set[str]:
        names = set(self.get_variables(repo))
        parts = repo.group.split("/")
        try:
            for i in range(1, len(parts) + 1):
                group = self._group("/".join(parts[:i]))
                if group is not None:
                    names |= {v.key for v in group.variables.list(get_all=True)}
        except gle.GitlabError as exc:
            raise self._wrap(exc) from exc
        return names

    # -- pull (merge) requests and pipelines ---------------------------------------------------

    def ensure_pull_request(
        self, repo: Repository, source: str, target: str, title: str, description: str
    ) -> PullRequest:
        project = self._p(repo)
        try:
            existing = project.mergerequests.list(
                state="opened", source_branch=source, target_branch=target, get_all=True
            )
            if existing:
                mr = existing[0]
                mr.title, mr.description = title, description
                mr.save()
            else:
                mr = project.mergerequests.create(
                    {
                        "source_branch": source,
                        "target_branch": target,
                        "title": title,
                        "description": description,
                    }
                )
        except gle.GitlabError as exc:
            raise self._wrap(exc) from exc
        return PullRequest(
            repo.path, mr.iid, source, target, title, description, getattr(mr, "web_url", "")
        )

    def file_url(self, repo: Repository, ref: str, path: str) -> str:
        return f"{repo.url.removesuffix('.git')}/-/blob/{ref}/{path}"

    def trigger_pipeline(self, repo: Repository, ref: str, variables: dict[str, str]) -> str:
        try:
            pipeline = self._p(repo).pipelines.create(
                {"ref": ref, "variables": [{"key": k, "value": v} for k, v in variables.items()]}
            )
        except gle.GitlabError as exc:
            raise self._wrap(exc) from exc
        return str(pipeline.id)
