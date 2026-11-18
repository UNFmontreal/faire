"""Indexing outside the platform: credentials come from the environment."""

import pytest
from click.testing import CliRunner

from faire import indexing
from faire.cli import main
from faire.platform.fake import FakePlatform
from indexfix import GROUP, git, received, remote_head, request

pytestmark = pytest.mark.integration

SAMPLE = {"01/003/a.dcm": "scan a\n"}
SECRET = "s3cr3t-value-that-must-not-leak"


@pytest.fixture
def platform(tmp_path):
    return FakePlatform(tmp_path / "hosting")


def test_a_missing_platform_credential_fails_before_anything_changes(
    project, platform, tmp_path, monkeypatch
):
    project.init(platform=platform, group=GROUP)
    before = remote_head(platform)
    monkeypatch.delenv("FAIRE_PLATFORM_TOKEN", raising=False)
    incoming = received(tmp_path, SAMPLE)
    result = CliRunner().invoke(
        main,
        [
            "index", str(incoming), "--stream", "dicoms", "--madmp", str(project.madmp),
            "--site", "a", "--sites-dir", str(project.sites_dir), "--platform", "gitlab",
            "--platform-url", "https://gitlab.example.org", "--group", GROUP,
        ],
    )  # fmt: skip
    assert result.exit_code == 1
    assert "FAIRE_PLATFORM_TOKEN" in result.output
    assert remote_head(platform) == before


def storage_with_secret(project):
    project.hosts["Site storage"]["secrets"] = {"password": "SITE_A_STORAGE_PASSWORD"}
    project.write()


def test_a_missing_storage_credential_fails_naming_it_and_changes_nothing(
    project, platform, tmp_path
):
    storage_with_secret(project)
    project.init(platform=platform, group=GROUP)
    before = remote_head(platform)
    with pytest.raises(indexing.IndexingError, match="SITE_A_STORAGE_PASSWORD") as raised:
        indexing.index(request(project, platform, received(tmp_path, SAMPLE), env={}))
    assert SECRET not in str(raised.value)
    assert remote_head(platform) == before
    assert not list(tmp_path.glob("faire-index-*"))  # nothing was even cloned


def test_with_the_credential_present_the_value_is_never_recorded(project, platform, tmp_path):
    storage_with_secret(project)
    project.init(platform=platform, group=GROUP)
    env = {"SITE_A_STORAGE_PASSWORD": SECRET}
    out = indexing.index(request(project, platform, received(tmp_path, SAMPLE), env=env))
    assert out.commit
    url = platform.get_repository(GROUP, "dicoms-a_PrismaFit16001").url
    assert SECRET not in git(url, "log", "--all", "-p")
    assert SECRET not in indexing.report(out)
