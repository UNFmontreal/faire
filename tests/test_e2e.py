"""The whole path on the test platform: from received files to release records in the ma-DMP."""

from pathlib import Path

import pytest
from click.testing import CliRunner
from datalad.api import clone

from faire import indexing, model
from faire.cli import main
from faire.platform.fake import FakePlatform
from indexfix import git, received, request
from lifefix import GROUP, accept_through_chain, invoke, runner

pytestmark = pytest.mark.integration


@pytest.fixture
def platform(tmp_path):
    return FakePlatform(tmp_path / "hosting")


def test_single_site_pilot_and_production_samples_to_release_records(
    project, platform, tmp_path, monkeypatch
):
    standardized = next(
        d for d in project.doc["dmp"]["dataset"] if d["dataset_id"]["identifier"] == "standardized"
    )
    standardized["distribution"] = [  # the example's Zenodo needs a token this test has not got
        d for d in standardized["distribution"] if d["faire"]["stage"] != "release"
    ]
    store = project.add_stage_distribution("standardized", "release", "Release store")
    project.init(platform=platform, group=GROUP)

    pilot = indexing.index(
        request(
            project,
            platform,
            received(tmp_path, {"01/001/scan.txt": "p\n", "01/001/PILOT": ""}, "p"),
        )
    )
    assert pilot.pilot
    indexing.index(request(project, platform, received(tmp_path, {"01/003/scan.txt": "scan\n"})))
    accept_through_chain(project, platform, monkeypatch, tmp_path)

    out = invoke(
        platform, monkeypatch, "release", "v1", "--site", "a",
        "--platform-url", "https://x", "--group", GROUP,
    )  # fmt: skip
    assert out.exit_code == 0, out.output
    instance = platform.get_repository(GROUP, "dicoms-a_PrismaFit16001").url
    assert git(instance, "tag", "--contains", pilot.commit) == ""  # no pilot sample is released

    # the release is delivered, and what that established is written to the ma-DMP
    std = runner(project, platform, tmp_path, "standardized", "main", name="delivery")
    std.get(".", recursive=False, result_renderer="disabled")  # this runner holds the content
    study = clone(
        platform.get_repository(GROUP, "study").url,
        str(tmp_path / "study"),
        result_renderer="disabled",
    )
    args = ["sync", "--stage", "release", "--dataset", std.path, "--madmp", str(project.madmp)]
    args += [
        "--site",
        "a",
        "--sites-dir",
        str(project.sites_dir),
        "--tag",
        "v1",
        "--study",
        study.path,
    ]
    done = CliRunner().invoke(main, args)
    assert done.exit_code == 0, done.output
    assert any(store.rglob("*")), "the released files reached the release host"
    dataset = model.load(Path(study.path) / "madmp.json").dataset("standardized")
    (record,) = dataset.releases
    assert record["id"] == "v1" and record["revision"] == git(std.path, "rev-parse", "v1")
    assert next(d for d in dataset.distributions if d.title == "Release store").raw["issued"]
