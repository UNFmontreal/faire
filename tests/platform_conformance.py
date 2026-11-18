"""Conformance suite every platform implementation must pass.

Concrete test modules subclass `PlatformConformance` and provide a `platform` fixture.
"""

import pytest

from faire.platform import PlatformError, UnsupportedOperation


class PlatformConformance:
    def seed(self, platform, repo, *branches):
        """Make the branches exist in the repository; only a real platform needs it."""

    def test_group_and_repository_are_created_once(self, platform):
        group = platform.ensure_group("study/nested")
        repo = platform.ensure_repository(group.path, "bids")
        again = platform.ensure_repository(group.path, "bids")
        assert repo == again
        assert platform.get_repository(group.path, "bids") == repo
        assert platform.get_repository(group.path, "absent") is None
        assert repo.url

    def test_ensure_group_is_idempotent(self, platform):
        assert platform.ensure_group("study") == platform.ensure_group("study")

    def test_variables_created_and_updated(self, platform):
        repo = platform.ensure_repository(platform.ensure_group("grp").path, "repo")
        platform.set_variable(repo, "FAIRE_A", "1")
        platform.set_variable(repo, "FAIRE_B", "x", protected_refs_only=True)
        platform.set_variable(repo, "FAIRE_A", "2")
        assert platform.get_variables(repo) == {"FAIRE_A": "2", "FAIRE_B": "x"}

    def test_defined_variables_include_group_variables(self, platform):
        group = platform.ensure_group("study/nested")
        repo = platform.ensure_repository(group.path, "repo")
        platform.set_variable(repo, "OWN", "1")
        platform.set_group_variable("study", "FROM_GROUP", "x")
        assert platform.defined_variables(repo) == {"OWN", "FROM_GROUP"}

    def test_branch_and_tag_protection(self, platform):
        repo = platform.ensure_repository(platform.ensure_group("grp").path, "repo")
        for pattern in ("dev", "main"):
            result = platform.protect_branch(repo, pattern, approvals=1)
            assert result.pattern == pattern
        platform.protect_branch(repo, "dev", approvals=1)  # again, no error
        platform.protect_tag(repo, "*")
        platform.protect_tag(repo, "*")

    def test_merge_policy_can_be_set_repeatedly(self, platform):
        repo = platform.ensure_repository(platform.ensure_group("grp").path, "repo")
        platform.set_merge_policy(repo)
        platform.set_merge_policy(repo)

    def test_file_url_names_the_branch_and_path(self, platform):
        platform.ensure_group("grp")
        repo = platform.ensure_repository(platform.ensure_group("grp").path, "repo")
        url = platform.file_url(repo, "feature/x", "01/report.html")
        assert url.endswith("feature/x/01/report.html") and "grp/repo" in url

    def test_pull_request_created_then_updated(self, platform):
        repo = platform.ensure_repository(platform.ensure_group("grp").path, "repo")
        self.seed(platform, repo, "dev", "feature/s1", "feature/s2")
        first = platform.ensure_pull_request(repo, "feature/s1", "dev", "S1", "one")
        second = platform.ensure_pull_request(repo, "feature/s1", "dev", "S1", "two")
        other = platform.ensure_pull_request(repo, "feature/s2", "dev", "S2", "x")
        assert first.number == second.number != other.number
        assert second.description == "two"

    def test_open_pull_requests_are_listed(self, platform):
        repo = platform.ensure_repository(platform.ensure_group("grp").path, "repo")
        self.seed(platform, repo, "dev", "feature/s1")
        assert platform.open_pull_requests(repo) == []
        pr = platform.ensure_pull_request(repo, "feature/s1", "dev", "S1", "one")
        assert [(p.number, p.source, p.target) for p in platform.open_pull_requests(repo)] == [
            (pr.number, "feature/s1", "dev")
        ]

    def test_trigger_pipeline(self, platform):
        repo = platform.ensure_repository(platform.ensure_group("grp").path, "repo")
        self.seed(platform, repo, "dev")
        assert platform.trigger_pipeline(repo, "dev", {"SAMPLE": "s1"})

    def test_capability_check_names_unsupported_operations(self, platform):
        platform.require(["ensure_group"])
        platform.supported = platform.supported - {"trigger_pipeline", "protect_tag"}
        with pytest.raises(UnsupportedOperation) as err:
            platform.require(["ensure_group", "trigger_pipeline", "protect_tag"])
        assert err.value.operations == ["trigger_pipeline", "protect_tag"]
        assert isinstance(err.value, PlatformError)
