from pathlib import Path

import pytest
from datalad.api import Dataset, clone

from faire.platform import UnsupportedOperation
from faire.platform.fake import FakePlatform

pytestmark = pytest.mark.integration

GROUP = "example-study"


@pytest.fixture
def platform(tmp_path):
    return FakePlatform(tmp_path / "hosting")


def test_init_creates_repositories_and_study_resolves_from_platform(project, platform, tmp_path):
    result = project.init(platform=platform, group=GROUP, faire_image="reg/faire:1")
    names = {r.name for r in (e.repo for e in platform.repos.values())}
    assert names == {"dicoms-a_PrismaFit16001", "atlas", "standardized", "analysis", "study"}
    # a fresh clone of the study from the platform resolves every subdataset
    study = platform.get_repository(GROUP, "study")
    fresh = clone(study.url, str(tmp_path / "fresh"), result_renderer="disabled")
    fresh.get(".", get_data=False, recursive=True, result_renderer="disabled")
    for where in ("standardized", "analysis", "atlas", "dicoms/a_PrismaFit16001"):
        assert Dataset(Path(fresh.path) / where).is_installed(), where
    # subdataset references point at platform repositories
    modules = (Path(fresh.path) / ".gitmodules").read_text()
    assert platform.get_repository(GROUP, "standardized").url in modules
    # derived datasets reference their sources on the platform
    ana = Dataset(project.ws.repos / "analysis")
    assert (
        platform.get_repository(GROUP, "standardized").url
        in (Path(ana.path) / ".gitmodules").read_text()
    )
    # branches reached the platform
    std = platform.get_repository(GROUP, "standardized")
    published = Dataset(project.ws.repos / "standardized").repo.call_git(
        ["ls-remote", "--heads", std.url]
    )
    assert all(f"refs/heads/{b}" in published for b in ("dev", "pilot", "main"))
    assert not result.differences


def test_ci_variables_derive_from_the_madmp(project, platform):
    project.init(platform=platform, group=GROUP, faire_image="reg/faire:1")
    std = platform.get_repository(GROUP, "standardized")
    variables = platform.get_variables(std)
    assert variables["FAIRE_DATASET"] == "standardized"
    assert variables["FAIRE_SOURCES"] == "dicoms-a_PrismaFit16001"
    assert variables["FAIRE_DOWNSTREAM"] == f"{GROUP}/analysis"
    assert variables["FAIRE_SECRETS"] == "ZENODO_TOKEN"
    assert variables["FAIRE_IMAGE"] == "reg/faire:1"
    inst = platform.get_variables(platform.get_repository(GROUP, "dicoms-a_PrismaFit16001"))
    assert inst["FAIRE_DOWNSTREAM"] == f"{GROUP}/standardized"


def test_protection_of_branches_tags_and_sample_branches(project, platform):
    result = project.init(platform=platform, group=GROUP)
    for name in ("standardized", "study"):
        repo = platform.get_repository(GROUP, name)
        branches = platform.protected_branches(repo)
        assert branches == {"dev": 1, "pilot": 1, "main": 1, "feature/*": 0}
        assert platform.protected_tags(repo) == {"*"}
        assert platform.merge_policy(repo)  # pipelines must pass; merge commits only
    assert not result.notes


def test_study_validation_runs_in_the_tool_image_and_is_required(project, platform):
    project.init(platform=platform, group=GROUP, faire_image="reg/faire:1")
    study = platform.get_repository(GROUP, "study")
    assert platform.get_variables(study) == {"FAIRE_IMAGE": "reg/faire:1"}
    assert platform.merge_policy(study)
    ci = (project.ws.study / ".gitlab-ci.yml").read_text()
    assert "faire validate madmp.json" in ci and "merge_request_event" in ci


def test_approvals_unavailable_is_reported(project, tmp_path):
    platform = FakePlatform(tmp_path / "h2", supports_approvals=False)
    result = project.init(platform=platform, group=GROUP)
    assert any("maintainers" in n for n in result.notes)


def test_unsupported_operation_fails_before_any_change(project, platform):
    platform.supported = platform.supported - {"protect_tag"}
    with pytest.raises(UnsupportedOperation, match="protect_tag"):
        project.init(platform=platform, group=GROUP)
    assert not project.ws.root.exists()
    assert not platform.repos and not platform.groups


def test_missing_secrets_reported_with_repositories(project, platform):
    first = project.init(platform=platform, group=GROUP)
    assert first.missing_secrets == {"ZENODO_TOKEN": [f"{GROUP}/standardized"]}
    platform.set_group_variable(GROUP, "ZENODO_TOKEN", "defined-by-operators")
    assert project.init(platform=platform, group=GROUP).missing_secrets == {}
    # the tool never stores a secret value
    for entry in platform.repos.values():
        assert "defined-by-operators" not in entry.variables.values().__repr__()


def test_second_run_with_platform_changes_nothing(project, platform):
    project.init(platform=platform, group=GROUP)
    again = project.init(platform=platform, group=GROUP)
    assert not again.actions
