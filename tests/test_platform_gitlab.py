import pytest
import requests

from faire.platform.gitlab import GitLabPlatform
from fake_gitlab import FakeGitLab
from platform_conformance import PlatformConformance


def make(approvals=True):
    adapter = FakeGitLab(approvals_available=approvals)
    session = requests.Session()
    session.mount("https://gitlab.test", adapter)
    platform = GitLabPlatform("https://gitlab.test", "token", session=session)
    platform.set_group_variable = lambda group, key, value: adapter.group_variables.setdefault(
        group, {}
    ).__setitem__(key, {"key": key, "value": value})
    return platform, adapter


class TestGitLabAgainstInProcessApi(PlatformConformance):
    @pytest.fixture
    def platform(self):
        return make()[0]

    def test_nested_groups_get_parent_ids(self):
        platform, adapter = make()
        platform.ensure_group("lab/study")
        assert set(adapter.groups) == {"lab", "lab/study"}
        assert adapter.groups["lab/study"]["full_path"] == "lab/study"

    def test_protection_levels_and_approval_rule(self):
        platform, adapter = make()
        repo = platform.ensure_repository(platform.ensure_group("g").path, "r")
        result = platform.protect_branch(repo, "dev", approvals=1)
        project = next(iter(adapter.projects.values()))
        assert result.approvals_enforced
        assert project["branches"]["dev"]["push_access_level"] == 40
        assert project["branches"]["dev"]["merge_access_level"] == 40
        assert project["branches"]["dev"]["allow_force_push"] is False
        assert project["approval_rules"][0]["approvals_required"] == 1
        platform.protect_tag(repo, "*")
        assert project["tags"]["*"]["create_access_level"] == 40

    def test_without_approval_rules_merges_stay_restricted(self):
        platform, adapter = make(approvals=False)
        repo = platform.ensure_repository(platform.ensure_group("g").path, "r")
        result = platform.protect_branch(repo, "main", approvals=1)
        assert not result.approvals_enforced and "maintainers" in result.notes[0]
        assert next(iter(adapter.projects.values()))["branches"]["main"]["merge_access_level"] == 40

    def test_pipeline_variables_are_sent(self):
        platform, adapter = make()
        repo = platform.ensure_repository(platform.ensure_group("g").path, "r")
        platform.trigger_pipeline(repo, "dev", {"SAMPLE": "s1"})
        sent = next(iter(adapter.projects.values()))["pipelines"][0]
        assert sent["ref"] == "dev" and sent["variables"] == [{"key": "SAMPLE", "value": "s1"}]
