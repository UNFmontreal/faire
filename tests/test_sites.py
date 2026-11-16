from pathlib import Path

import pytest
import yaml

from faire import model, sites

DATA = Path(__file__).parent / "data"

GOOD = {
    "site": "a",
    "hosts": {
        "Site storage": {"type": "directory", "parameters": {"directory": "/data/a"}},
        "Nas": {
            "type": "rsync",
            "parameters": {"rsyncurl": "nas:/x"},
            "secrets": {"password": "NAS_PW"},
        },
    },
    "runners": {"tags": ["site-a", "gpu"]},
}


def write(tmp_path, data, name="a.yaml"):
    path = tmp_path / name
    path.write_text(yaml.safe_dump(data))
    return path


def test_load_site_config(tmp_path):
    cfg = sites.load(write(tmp_path, GOOD))
    assert cfg.site == "a"
    assert cfg.runner_tags == ("site-a", "gpu")
    assert cfg.mapping("Site storage").type == "directory"
    assert cfg.mapping("Nas").secrets == {"password": "NAS_PW"}


def test_unmapped_host_is_reported_by_name(tmp_path):
    dmp = model.load(DATA / "single_site.json")
    cfg = sites.parse({"site": "a", "hosts": {}})
    assert sites.unmapped_hosts(dmp, cfg) == ["Site storage"]
    with pytest.raises(sites.SiteConfigError, match="Site storage"):
        sites.check_site(dmp, cfg)


def test_mapped_hosts_pass():
    dmp = model.load(DATA / "single_site.json")
    sites.check_site(dmp, sites.parse(GOOD))


def test_inline_credential_rejected():
    bad = {"site": "a", "hosts": {"S": {"type": "s3", "parameters": {"secret_key": "abc"}}}}
    with pytest.raises(sites.SiteConfigError, match="looks like a credential"):
        sites.parse(bad)
    bad = {"site": "a", "hosts": {"S": {"type": "s3", "secrets": {"secret_key": "has space!"}}}}
    with pytest.raises(sites.SiteConfigError, match="must name a secret"):
        sites.parse(bad)


def test_file_name_must_match_site(tmp_path):
    with pytest.raises(sites.SiteConfigError, match="file name"):
        sites.load(write(tmp_path, GOOD, name="b.yaml"))


def test_missing_site_identifier():
    with pytest.raises(sites.SiteConfigError, match="site"):
        sites.parse({"hosts": {}})


def test_load_all_from_study_root(tmp_path):
    (tmp_path / "sites").mkdir()
    write(tmp_path / "sites", GOOD)
    write(tmp_path / "sites", {**GOOD, "site": "b"}, name="b.yaml")
    assert set(sites.load_all(tmp_path)) == {"a", "b"}
