"""The platform conformance suite against a real GitLab (opt-in, marker `integration`).

Set FAIRE_TEST_GITLAB_URL, FAIRE_TEST_GITLAB_TOKEN (a group access token with the `api` scope,
Owner role) and FAIRE_TEST_GITLAB_GROUP (the existing group to work in). Every run creates one
uniquely named subgroup and deletes it afterwards.
"""

import os
import uuid

import gitlab
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
        """Push one commit to each branch through the platform's git credential helper."""
        from datalad.api import create

        work = create(str(self.tmp / repo.name), result_renderer="disabled")
        (self.tmp / repo.name / "f.txt").write_text("x\n")
        (self.tmp / repo.name / ".gitlab-ci.yml").write_text('noop:\n  script: ["true"]\n')
        work.save(message="seed", result_renderer="disabled")
        with platform.git_auth():
            for branch in branches:
                work.repo.call_git(["push", repo.url, f"HEAD:refs/heads/{branch}"])

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


# The instance's shared runner only runs a few images (alpine among them), so the study's
# validation job runs in alpine and installs the tool from its repository.
REF = os.environ.get("FAIRE_TEST_REF", "76b4c9b")
ALPINE_JOB = f"""  image: alpine:3
  before_script:
    - apk add --no-cache python3 py3-pip git
    - pip install --break-system-packages --no-cache-dir "git+https://github.com/UNFmontreal/faire@{REF}"
"""


def wait_for_pipeline(project, mr_iid, timeout=900):
    """The merge request's newest pipeline once it has finished."""
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        mr = project.mergerequests.get(mr_iid)
        pipeline = mr.head_pipeline
        if pipeline and pipeline["status"] in ("success", "failed", "canceled"):
            return mr, pipeline["status"]
        time.sleep(10)
    raise AssertionError(f"no finished pipeline for merge request {mr_iid} in {timeout}s")


def traces(project, mr):
    """Job logs of the merge request's pipeline, to show why a pipeline failed."""
    out = []
    for job in project.pipelines.get(mr.head_pipeline["id"]).jobs.list(get_all=True):
        trace = project.jobs.get(job.id).trace().decode(errors="replace")
        out.append(f"--- {job.name} ({job.status})\n{trace[-1500:]}")
    return "\n".join(out)


def test_invalid_madmp_edit_cannot_be_merged_and_a_valid_one_can(platform, tmp_path):
    import json
    import subprocess
    from pathlib import Path

    from faire import validate as validation

    root = Path(__file__).parent.parent
    document = json.loads((root / "tests/data/single_site.json").read_text())
    assert validation.validate(document) == []

    def git(*args):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    def write(doc):
        (tmp_path / "madmp.json").write_text(json.dumps(doc, indent=2) + "\n")

    repo = platform.ensure_repository(platform.ensure_group("grp").path, "study")
    git("init", "-q", "-b", "main")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.org")
    template = (root / "templates/study/template/.gitlab-ci.yml").read_text()
    assert "  image: $FAIRE_IMAGE\n" in template
    (tmp_path / ".gitlab-ci.yml").write_text(
        template.replace("  image: $FAIRE_IMAGE\n", ALPINE_JOB)
    )
    write(document)
    git("add", ".")
    git("commit", "-q", "-m", "study")
    with platform.git_auth():
        git("push", "-q", repo.url, "main")
    platform.protect_branch(repo, "main")
    platform.set_merge_policy(repo)

    valid = json.loads(json.dumps(document))
    valid["dmp"]["title"] = "A better title"
    invalid = json.loads(json.dumps(document))
    del invalid["dmp"]["contact"]
    assert validation.validate(invalid), "the edit must be invalid"
    numbers = {}
    for branch, doc in (("edit-valid", valid), ("edit-invalid", invalid)):
        git("checkout", "-q", "-b", branch, "main")
        write(doc)
        git("commit", "-q", "-am", branch)
        with platform.git_auth():
            git("push", "-q", repo.url, branch)
        numbers[branch] = platform.ensure_pull_request(repo, branch, "main", branch, "").number

    project = platform.gl.projects.get(f"{repo.group}/{repo.name}")
    bad, bad_status = wait_for_pipeline(project, numbers["edit-invalid"])
    assert bad_status == "failed", traces(project, bad)
    assert "faire validate" in traces(project, bad)  # it failed in the check, not before it
    assert "contact" in traces(project, bad)  # and the violation is shown
    assert bad.detailed_merge_status != "mergeable"
    with pytest.raises(gitlab.exceptions.GitlabError) as refused:
        bad.merge()
    assert refused.value.response_code in (405, 406)  # not mergeable: its pipeline failed

    good, good_status = wait_for_pipeline(project, numbers["edit-valid"])
    assert good_status == "success", traces(project, good)
    good.merge()
    assert project.mergerequests.get(numbers["edit-valid"]).state == "merged"


def wait_for_branch_pipeline(project, ref, timeout=600):
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        pipelines = project.pipelines.list(ref=ref, get_all=False)
        if pipelines and pipelines[0].status in ("success", "failed", "canceled"):
            return project.pipelines.get(pipelines[0].id)
        time.sleep(8)
    raise AssertionError(f"no finished pipeline on {ref} in {timeout}s")


def test_protected_variable_is_visible_to_sample_branches_only(platform, tmp_path):
    import subprocess

    from faire.bootstrap import PROTECTED_BRANCHES, SAMPLE_BRANCHES

    def git(*args):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    repo = platform.ensure_repository(platform.ensure_group("grp").path, "dataset")
    git("init", "-q", "-b", "main")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.org")
    (tmp_path / ".gitlab-ci.yml").write_text(
        'probe:\n  image: alpine:3\n  script:\n    - echo "secret-length:${#STORAGE_SECRET}"\n'
    )
    git("add", ".")
    git("commit", "-q", "-m", "probe")
    with platform.git_auth():
        git("push", "-q", repo.url, "main")
    # what `faire init` configures: the tool's branch patterns protected, the secret protected
    for pattern in PROTECTED_BRANCHES:
        platform.protect_branch(repo, pattern, approvals=0)
    platform.protect_branch(repo, SAMPLE_BRANCHES, approvals=0)
    platform.set_variable(repo, "STORAGE_SECRET", "not-a-real-secret", protected_refs_only=True)
    for branch in ("feature/subject-01", "tweak-by-someone"):
        git("checkout", "-q", "-b", branch, "main")
        git("commit", "-q", "--allow-empty", "-m", branch)
        with platform.git_auth():
            git("push", "-q", repo.url, branch)

    project = platform.gl.projects.get(f"{repo.group}/{repo.name}")

    def seen(branch):
        pipeline = wait_for_branch_pipeline(project, branch)
        log = project.jobs.get(pipeline.jobs.list()[0].id).trace().decode(errors="replace")
        assert pipeline.status == "success", log
        return "secret-length:17\n" in log.replace("\r", ""), "secret-length:0\n" in log.replace(
            "\r", ""
        )

    assert seen("feature/subject-01") == (True, False)  # a sample branch reads the secret
    assert seen("tweak-by-someone") == (False, True)  # an arbitrary branch does not
