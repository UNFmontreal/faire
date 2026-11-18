from pathlib import Path

import pytest
import yaml
from datalad.api import Dataset, clone

from faire import bootstrap

pytestmark = pytest.mark.integration

SENSITIVE_ONLY = "metadata=distribution-restrictions=sensitive"


def repo(project, name):
    return Dataset(project.ws.repos / name)


def test_creates_datasets_with_record_and_branches(project):
    result = project.init()
    assert result
    for name in ("dicoms-a_PrismaFit16001", "atlas", "standardized", "analysis"):
        ds = repo(project, name)
        assert ds.is_installed()
        assert {"dev", "pilot", "main"} <= set(ds.repo.get_branches())
    ds = repo(project, "standardized")
    record = yaml.safe_load((Path(ds.path) / bootstrap.RECORD).read_text())
    assert record["dataset_id"] == "standardized"
    assert record["template"]["version"] == "v1"
    assert record["sources"] == [
        {
            "path": "sourcedata/dicoms/a_PrismaFit16001",
            "key": "dicoms/a_PrismaFit16001",
            "role": "triggering",
        }
    ]
    assert record["license"] == "https://spdx.org/licenses/CC-BY-4.0"
    answers = yaml.safe_load((Path(ds.path) / ".copier-answers.yml").read_text())
    assert answers["dataset_id"] == "standardized"


def test_template_fetch_failure_leaves_nothing(project):
    project.doc["dmp"]["dataset"][2]["faire"]["template"]["repository"] = str(
        project.tmp / "no-such-template"
    )
    with pytest.raises(Exception, match="no-such-template"):
        project.init()
    assert not (project.ws.repos / "standardized").exists()


def test_sources_installed_under_sourcedata(project):
    project.init()
    std = repo(project, "standardized")
    assert sorted(
        Path(s["path"]).relative_to(std.path).as_posix()
        for s in std.subdatasets(result_renderer="disabled", return_type="list")
    ) == ["code/containers", "sourcedata/dicoms/a_PrismaFit16001"]  # the collection and the source
    assert (Path(std.path) / "sourcedata/dicoms").is_dir()
    assert not Dataset(Path(std.path) / "sourcedata/dicoms").is_installed()  # plain directory
    assert Dataset(Path(std.path) / "sourcedata/dicoms/a_PrismaFit16001").is_installed()
    ana = repo(project, "analysis")
    subs = {
        Path(s["path"]).relative_to(ana.path).as_posix()
        for s in ana.subdatasets(result_renderer="disabled", return_type="list")
    }
    assert subs == {"code/containers", "sourcedata/standardized", "sourcedata/atlas"}
    atlas = repo(project, "atlas").subdatasets(result_renderer="disabled", return_type="list")
    assert [Path(s["path"]).name for s in atlas] == [
        "containers"
    ]  # no sources, only the collection


def test_study_superdataset_clone_installs_everything(project, tmp_path):
    project.init()
    study = Dataset(project.ws.study)
    assert (Path(study.path) / "madmp.json").read_text() == project.madmp.read_text()
    assert (Path(study.path) / "sites" / "a.yaml").exists()
    fresh = clone(str(project.ws.study), str(tmp_path / "fresh"), result_renderer="disabled")
    fresh.get(".", get_data=False, recursive=True, result_renderer="disabled")
    for where in ("standardized", "analysis", "atlas", "dicoms/a_PrismaFit16001"):
        assert Dataset(Path(fresh.path) / where).is_installed(), where


def test_storage_remotes_with_wanted_rules(project):
    project.doc["dmp"]["dataset"][2]["distribution"].insert(
        0,
        {
            "title": "Sensitive store",
            "data_access": "closed",
            "license": [{"license_ref": "https://x.org/l", "start_date": "2026-01-01"}],
            "host": {"title": "Site storage", "faire": {"site_dependent": True}},
            "faire": {
                "stage": "accepted",
                "filter": "metadata=distribution-restrictions=sensitive",
            },
        },
    )
    project.write()
    project.init()
    repo_ = repo(project, "standardized").repo
    remotes = {r["name"] for r in repo_.get_special_remotes().values()}
    assert remotes == {"review-site-storage", "accepted-site-storage"}  # no release/archival
    assert repo_.get_preferred_content("wanted", "review-site-storage") == (
        "not metadata=distribution-restrictions=sensitive"
    )
    assert repo_.get_preferred_content("wanted", "accepted-site-storage") == SENSITIVE_ONLY
    assert (project.storage / "standardized").is_dir()


def heads(project):
    out = {}
    for path in sorted(project.ws.repos.iterdir()):
        repo_ = Dataset(path).repo
        out[path.name] = (repo_.get_hexsha("HEAD"), repo_.get_hexsha("git-annex"))
    study = Dataset(project.ws.study).repo
    out["study"] = (study.get_hexsha("HEAD"), None)
    return out


def test_second_run_makes_no_change_and_no_commit(project):
    project.init()
    before = heads(project)
    again = project.init()
    assert not again.actions
    assert heads(project) == before


def test_dry_run_reports_without_creating(project):
    result = project.init(dry_run=True)
    assert any("create dataset standardized" in a for a in result.actions)
    assert any("create study superdataset" in a for a in result.actions)
    assert not project.ws.root.exists() or not any(project.ws.root.iterdir())
    assert not project.storage.exists()


def commit_state(project, names):
    out = {}
    for name in names:
        path = Path(repo(project, name).path)
        out[name] = (
            repo(project, name).repo.get_hexsha("HEAD"),
            sorted(p.name for p in path.iterdir()),
        )
    return out


def test_additive_new_dataset_and_distribution(project):
    project.init()
    names = ["dicoms-a_PrismaFit16001", "atlas", "standardized", "analysis"]
    before = commit_state(project, names)
    # a new derived dataset
    new = {
        "title": "Extra derivative",
        "dataset_id": {"identifier": "extra", "type": "other"},
        "personal_data": "no",
        "sensitive_data": "no",
        "related_identifier": [
            {"identifier": "standardized", "type": "other", "relation_type": "IsDerivedFrom"}
        ],
        "faire": {"template": project.doc["dmp"]["dataset"][2]["faire"]["template"]},
        "distribution": [
            {
                "title": "Working storage",
                "data_access": "closed",
                "license": [{"license_ref": "https://x.org/l", "start_date": "2026-01-01"}],
                "host": {"title": "Site storage", "faire": {"site_dependent": True}},
                "faire": {"stage": "accepted"},
            }
        ],
    }
    project.doc["dmp"]["dataset"].append(new)
    # a new distribution on an existing dataset
    project.doc["dmp"]["dataset"][1]["distribution"][0]["title"] = "Resource storage"
    project.doc["dmp"]["dataset"][3]["distribution"] = [
        {
            "title": "Analysis review",
            "data_access": "closed",
            "license": [{"license_ref": "https://x.org/l", "start_date": "2026-01-01"}],
            "host": {"title": "Site storage", "faire": {"site_dependent": True}},
            "faire": {"stage": "review"},
        }
    ]
    project.write()
    result = project.init()
    assert any("create dataset extra" in a for a in result.actions)
    assert not result.differences
    assert repo(project, "extra").is_installed()
    extra = repo(project, "extra")
    assert sorted(
        Path(s["path"]).relative_to(extra.path).as_posix()
        for s in extra.subdatasets(result_renderer="disabled", return_type="list")
    ) == ["code/containers", "sourcedata/standardized"]
    remotes = repo(project, "analysis").repo.get_special_remotes().values()
    assert {r["name"] for r in remotes} == {"accepted-site-storage", "review-site-storage"}
    after = commit_state(project, names)
    assert after == before  # existing datasets: same commits, same working tree
    assert Dataset(project.ws.study / "extra").is_installed()


def test_changed_sources_reported_and_left_untouched(project):
    project.init()
    before = repo(project, "analysis").repo.get_hexsha("HEAD")
    project.doc["dmp"]["dataset"][3]["related_identifier"] = [
        {"identifier": "atlas", "type": "other", "relation_type": "IsDerivedFrom"}
    ]
    project.write()
    result = project.init()
    assert any(d.startswith("analysis:") and "sources" in d for d in result.differences)
    assert repo(project, "analysis").repo.get_hexsha("HEAD") == before


def test_changed_template_version_reported(project):
    project.init()
    project.doc["dmp"]["dataset"][2]["faire"]["template"]["version"] = "v2"
    project.write()
    result = project.init()
    assert any(d.startswith("standardized:") and "template" in d for d in result.differences)


def test_removed_dataset_reported_not_deleted(project):
    project.init()
    del project.doc["dmp"]["dataset"][3]  # analysis
    project.write()
    result = project.init()
    assert "analysis: exists but is not in the ma-DMP" in result.differences
    assert repo(project, "analysis").is_installed()


def test_new_instrument_creates_instance_and_registration_branch(project):
    project.init()
    old = repo(project, "dicoms-a_PrismaFit16001")
    old_head = old.repo.get_hexsha("HEAD")
    std = repo(project, "standardized")
    std_main = std.repo.get_hexsha("main")
    project.doc["dmp"]["dataset"][0]["technical_resource"].append(
        {"name": "Skyra 2", "faire": {"instrument_id": "Skyra2", "site": "a"}}
    )
    project.write()
    result = project.init()
    assert not result.differences
    assert repo(project, "dicoms-a_Skyra2").is_installed()
    assert old.repo.get_hexsha("HEAD") == old_head  # existing instance untouched
    assert std.repo.get_hexsha("main") == std_main  # registration waits for review
    assert "register/a_Skyra2" in std.repo.get_branches()
    tree = std.repo.call_git(["ls-tree", "-r", "register/a_Skyra2", "--name-only"])
    assert "sourcedata/dicoms/a_Skyra2" in tree
    assert "sourcedata/dicoms/a_Skyra2" not in std.repo.call_git(
        ["ls-tree", "-r", "main", "--name-only"]
    )
    assert std.repo.get_active_branch() == "main"
    assert not project.init().actions  # the pending registration is not proposed twice


def test_license_and_readme_travel_with_the_dataset(project, tmp_path):
    project.init()
    fresh = clone(str(repo(project, "standardized").path), str(tmp_path / "alone"))
    root = Path(fresh.path)
    license_text = (root / "LICENSE").read_text()
    assert "SPDX-License-Identifier: CC-BY-4.0" in license_text
    assert "https://spdx.org/licenses/CC-BY-4.0" in license_text
    readme = (root / "README.md").read_text()
    assert "sourcedata/dicoms/a_PrismaFit16001" in readme
    assert "datalad get" in readme and "datalad rerun" in readme
    assert (
        "Nothing: this dataset holds collected data"
        in (Path(repo(project, "atlas").path) / "README.md").read_text()
    )


def test_spdx_id():
    assert bootstrap.spdx_id("https://spdx.org/licenses/CC0-1.0") == "CC0-1.0"
    assert bootstrap.spdx_id("https://example.org/my-license") == ""
    assert bootstrap.spdx_id(None) == ""


def test_init_command(project):
    from click.testing import CliRunner

    from conftest import STUDY_TEMPLATE
    from faire.cli import main

    args = [
        "init",
        str(project.madmp),
        "--site",
        "a",
        "--sites-dir",
        str(project.sites_dir),
        "--root",
        str(project.ws.root),
        "--study-template",
        str(STUDY_TEMPLATE),
    ]
    dry = CliRunner().invoke(main, [*args, "--dry-run"])
    assert dry.exit_code == 0 and "would: create dataset standardized" in dry.output
    assert not project.ws.root.exists()
    real = CliRunner().invoke(main, args)
    assert real.exit_code == 0, real.output
    again = CliRunner().invoke(main, args)
    assert again.exit_code == 0 and "no change" in again.output
    project.doc["dmp"]["dataset"][2]["faire"]["template"]["version"] = "v2"
    project.write()
    changed = CliRunner().invoke(main, args)
    assert changed.exit_code == 1 and "not applied: standardized" in changed.output
