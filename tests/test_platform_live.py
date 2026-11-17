"""The platform conformance suite against a real GitLab (opt-in, marker `integration`).

Set FAIRE_TEST_GITLAB_URL, FAIRE_TEST_GITLAB_TOKEN (a group access token with the `api` scope,
Owner role) and FAIRE_TEST_GITLAB_GROUP (the existing group to work in). Every run creates one
uniquely named subgroup and deletes it afterwards.
"""

import os
import uuid

import pytest

from faire.platform.gitlab import GitLabPlatform
from platform_conformance import PlatformConformance

URL = os.environ.get("FAIRE_TEST_GITLAB_URL")
TOKEN = os.environ.get("FAIRE_TEST_GITLAB_TOKEN")
PARENT = os.environ.get("FAIRE_TEST_GITLAB_GROUP")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not (URL and TOKEN and PARENT), reason="no live GitLab configured"),
]


class Sandboxed:
    """A GitLabPlatform whose top-level group names live inside the sandbox subgroup."""

    def __init__(self, platform: GitLabPlatform, prefix: str):
        self._platform, self._prefix = platform, prefix

    def __getattr__(self, name):
        return getattr(self._platform, name)

    def ensure_group(self, path):
        return self._platform.ensure_group(f"{self._prefix}/{path}")

    @property
    def supported(self):
        return self._platform.supported

    @supported.setter
    def supported(self, value):
        self._platform.supported = value

    def set_group_variable(self, group, key, value):
        self._platform.gl.groups.get(f"{self._prefix}/{group}").variables.create(
            {"key": key, "value": value}
        )


@pytest.fixture
def platform():
    real = GitLabPlatform(URL, TOKEN)
    prefix = f"{PARENT}/ci-{uuid.uuid4().hex[:8]}"
    real.ensure_group(prefix)
    yield Sandboxed(real, prefix)
    real.gl.groups.delete(prefix)


class TestGitLabLive(PlatformConformance):
    def seed(self, platform, repo, *branches):
        """Push one commit to each branch, with the token in a throwaway URL (never stored)."""
        from datalad.api import create

        work = create(str(self.tmp / repo.name), result_renderer="disabled")
        (self.tmp / repo.name / "f.txt").write_text("x\n")
        (self.tmp / repo.name / ".gitlab-ci.yml").write_text('noop:\n  script: ["true"]\n')
        work.save(message="seed", result_renderer="disabled")
        url = repo.url.replace("https://", f"https://oauth2:{TOKEN}@")
        for branch in branches:
            work.repo.call_git(["push", url, f"HEAD:refs/heads/{branch}"])

    @pytest.fixture(autouse=True)
    def _tmp(self, tmp_path):
        self.tmp = tmp_path

    def test_protection_is_maintainer_only_and_approvals_are_honest(self, platform):
        repo = platform.ensure_repository(platform.ensure_group("grp").path, "repo")
        self.seed(platform, repo, "dev")
        result = platform.protect_branch(repo, "dev", approvals=1)
        assert result.approvals_enforced or result.notes  # never silently claims enforcement
        branch = platform.gl.projects.get(repo.path).protectedbranches.get("dev")
        assert [x["access_level"] for x in branch.push_access_levels] == [40]
        assert [x["access_level"] for x in branch.merge_access_levels] == [40]
        assert not branch.allow_force_push

    def _lint(self, platform, content):
        repo = platform.ensure_repository(platform.ensure_group("grp").path, "repo")
        project = platform.gl.projects.get(repo.path)
        return project.ci_lint.create({"content": content})

    def test_dataset_template_pipeline_passes_the_ci_linter(self, platform):
        from conftest import DATASET_TEMPLATE

        text = (DATASET_TEMPLATE / "template" / ".gitlab-ci.yml").read_text()
        result = self._lint(platform, text)
        assert result.valid, result.errors

    def test_rendered_child_pipeline_passes_the_ci_linter(self, platform):
        from faire import ciplan
        from faire.render import gitlab as renderer

        plan = ciplan.CiPlan(
            "derived",
            "dev",
            (
                ciplan.Task("a:s=1", "a", {"s": "1"}, "a", 0, "feature/s-1", (".faire/logs/",)),
                ciplan.Task("b:s=1", "b", {"s": "1"}, "a", 1, "feature/s-1"),
                ciplan.Task("a:s=2", "a", {"s": "2"}, "b", 0, "feature/s-2"),
            ),
            (ciplan.Check("layout", True), ciplan.Check("extra", False)),
            ("study/other",),
        )
        result = self._lint(
            platform, renderer.render_yaml(plan, {"a": ["site-a"], "b": ["site-b"]})
        )
        assert result.valid, result.errors
