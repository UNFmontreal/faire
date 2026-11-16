import copy
import json
from pathlib import Path

from faire import model, plan

DATA = Path(__file__).parent / "data"


def two_streams():
    """federated example plus a second stream fed by PrismaFit16001 and a dataset using both."""
    doc = json.loads((DATA / "federated.json").read_text())
    datasets = doc["dmp"]["dataset"]
    dicoms = next(d for d in datasets if d["dataset_id"]["identifier"] == "dicoms")
    mri_raw = copy.deepcopy(dicoms)
    mri_raw["dataset_id"]["identifier"] = "mri_raw"
    mri_raw["technical_resource"] = [dicoms["technical_resource"][0]]
    datasets.insert(0, mri_raw)
    std = next(d for d in datasets if d["dataset_id"]["identifier"] == "standardized")
    std["related_identifier"].append(
        {"identifier": "mri_raw", "type": "other", "relation_type": "IsDerivedFrom"}
    )
    return model.Dmp(doc)


def test_order_instances_and_paths():
    items = plan.creation_plan(two_streams(), "a")
    keys = [i.key for i in items]
    assert keys == [
        "mri_raw/a_PrismaFit16001",
        "dicoms/a_PrismaFit16001",
        "dicoms/b_Skyra45012",
        "dicoms/b_PhysioBox7",
        "atlas",
        "standardized",
        "analysis",
    ]
    std = items[keys.index("standardized")]
    assert [(s.path, s.role) for s in std.sources] == [
        ("sourcedata/dicoms/a_PrismaFit16001", "triggering"),
        ("sourcedata/dicoms/b_Skyra45012", "triggering"),
        ("sourcedata/dicoms/b_PhysioBox7", "triggering"),
        ("sourcedata/mri_raw/a_PrismaFit16001", "triggering"),
    ]


def test_same_instrument_in_two_streams_gives_distinct_repositories():
    items = {i.key: i for i in plan.creation_plan(two_streams(), "a")}
    a, b = items["dicoms/a_PrismaFit16001"], items["mri_raw/a_PrismaFit16001"]
    assert a.repo_name != b.repo_name
    assert (a.instance, a.stream) == ("a_PrismaFit16001", "dicoms")


def test_own_instruments_created_others_referenced():
    items = {i.key: i for i in plan.creation_plan(two_streams(), "a")}
    assert items["dicoms/a_PrismaFit16001"].create
    assert not items["dicoms/b_Skyra45012"].create
    other = {i.key: i for i in plan.creation_plan(two_streams(), "b")}
    assert other["dicoms/b_Skyra45012"].create and not other["dicoms/a_PrismaFit16001"].create


def test_resource_and_root_and_derived():
    dmp = model.load(DATA / "single_site.json")
    items = {i.key: i for i in plan.creation_plan(dmp, "a")}
    assert items["atlas"].sources == ()
    roles = {s.path: s.role for s in items["analysis"].sources}
    assert roles == {"sourcedata/standardized": "triggering", "sourcedata/atlas": "resource"}
    keys = list(items)
    assert keys.index("standardized") < keys.index("analysis")
    assert keys.index("dicoms/a_PrismaFit16001") < keys.index("standardized")


def test_instrument_stream_has_no_repository_of_its_own():
    items = plan.creation_plan(model.load(DATA / "single_site.json"), "a")
    assert "dicoms" not in [i.key for i in items]
