import json
from pathlib import Path

import pytest

from faire import model

DATA = Path(__file__).parent / "data"
EXAMPLES = ["single_site.json", "federated.json"]


@pytest.mark.parametrize("name", EXAMPLES)
def test_round_trip_leaves_document_unchanged(name, tmp_path):
    original = json.loads((DATA / name).read_text())
    dmp = model.load(DATA / name)
    out = tmp_path / name
    model.dump(dmp, out)
    assert json.loads(out.read_text()) == original
    assert out.read_text() == (DATA / name).read_text()


def test_unknown_fields_survive_round_trip():
    doc = json.loads((DATA / "single_site.json").read_text())
    doc["dmp"]["dataset"][0]["x_other"] = {"keep": [1, 2]}
    dmp = model.loads(json.dumps(doc))
    assert json.loads(model.dumps(dmp))["dmp"]["dataset"][0]["x_other"] == {"keep": [1, 2]}


def test_single_site_accessors():
    dmp = model.load(DATA / "single_site.json")
    assert dmp.sample_entities == ["subject", "session"]
    assert dmp.hub_host is None
    std = dmp.dataset("standardized")
    assert [s.dataset_id for s in dmp.sources_of(std)] == ["dicoms"]
    assert std.template.version == "v1.2.0"
    assert std.template.parameters == {"container": "converter"}
    assert std.license == "https://spdx.org/licenses/CC-BY-4.0"
    assert [d.stage for d in std.distributions] == ["review", "release", "archival"]
    review = std.distributions_at("review")[0]
    assert review.filter == "not metadata=distribution-restrictions=sensitive"
    assert std.distributions_at("archival")[0].host.long_term
    assert std.distributions_at("release")[0].host.secrets == {"token": "ZENODO_TOKEN"}
    assert std.distributions_at("review")[0].host.site_dependent


def test_source_roles_and_derived_datasets():
    dmp = model.load(DATA / "single_site.json")
    roles = {s.dataset_id: s.role for s in dmp.sources_of(dmp.dataset("analysis"))}
    assert roles == {"standardized": "triggering", "atlas": "resource"}
    assert [d.id for d in dmp.derived_datasets("standardized")] == ["analysis"]


def test_instruments_and_federation():
    dmp = model.load(DATA / "federated.json")
    dic = dmp.dataset("dicoms")
    assert dic.is_instrument_source
    assert [(i.instrument_id, i.site) for i in dic.instruments] == [
        ("PrismaFit16001", "a"),
        ("Skyra45012", "b"),
        ("PhysioBox7", "b"),
    ]
    assert dmp.hub_host == "hub" and dmp.coordinator == "a"
    hub = dmp.dataset("standardized").distributions_at("accepted")[0]
    assert hub.two_way and hub.host.host_id == "hub"


def test_write_back_is_visible_in_document():
    dmp = model.load(DATA / "single_site.json")
    std = dmp.dataset("standardized")
    std.add_release({"id": "r1", "date": "2026-07-01", "revision": "abc"})
    std.add_release({"id": "r1", "date": "2026-07-02", "revision": "abc"})
    std.distributions_at("release")[0].record_delivery(issued="2026-07-02", byte_size=10)
    doc = json.loads(model.dumps(dmp))
    ds = doc["dmp"]["dataset"][2]
    assert ds["faire"]["releases"] == [{"id": "r1", "date": "2026-07-02", "revision": "abc"}]
    assert ds["distribution"][1]["issued"] == "2026-07-02"
    assert ds["distribution"][1]["byte_size"] == 10
