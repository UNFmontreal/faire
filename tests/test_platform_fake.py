import pytest

from faire.platform.fake import FakePlatform
from platform_conformance import PlatformConformance


class TestFakePlatform(PlatformConformance):
    @pytest.fixture
    def platform(self, tmp_path):
        return FakePlatform(tmp_path / "hosting")

    def test_repositories_are_real_bare_git_repositories(self, platform):
        repo = platform.ensure_repository(platform.ensure_group("g").path, "r")
        from datalad.support.gitrepo import GitRepo

        assert GitRepo(repo.url, create=False).bare

    def test_approvals_not_enforceable_is_reported(self, tmp_path):
        platform = FakePlatform(tmp_path / "h", supports_approvals=False)
        repo = platform.ensure_repository(platform.ensure_group("g").path, "r")
        result = platform.protect_branch(repo, "main", approvals=1)
        assert not result.approvals_enforced and result.notes
