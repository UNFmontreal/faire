import copy
import json
from importlib import resources
from pathlib import Path

import jsonschema
import pytest

DATA = Path(__file__).parent / "data"
SCHEMA = resources.files("faire") / "schema"
EXAMPLES = ["single_site.json", "federated.json"]


def load(name):
    return json.loads((DATA / name).read_text())


def schema(name):
    return json.loads((SCHEMA / name).read_text())


def validator(name):
    s = schema(name)
    cls = jsonschema.validators.validator_for(s)
    cls.check_schema(s)
    return cls(s)


@pytest.mark.parametrize("example", EXAMPLES)
def test_example_valid_under_base_and_profile(example):
    doc = load(example)
    assert not list(validator("maDMP-schema-1.3.json").iter_errors(doc))
    assert not list(validator("faire-profile-1.json").iter_errors(doc))


@pytest.mark.parametrize("name", ["ex9-dmp-long.json", "ex7-dataset-many.json"])
def test_official_examples_valid_under_base(name):
    doc = json.loads((SCHEMA / name).read_text())
    assert not list(validator("maDMP-schema-1.3.json").iter_errors(doc))


def test_profile_rejects_unknown_stage():
    doc = copy.deepcopy(load("single_site.json"))
    doc["dmp"]["dataset"][2]["distribution"][0]["faire"]["stage"] = "bogus"
    assert list(validator("faire-profile-1.json").iter_errors(doc))


def test_profile_requires_sample_entities():
    doc = copy.deepcopy(load("single_site.json"))
    del doc["dmp"]["faire"]["sample_entities"]
    assert list(validator("faire-profile-1.json").iter_errors(doc))


def test_profile_requires_instrument_site():
    doc = copy.deepcopy(load("single_site.json"))
    del doc["dmp"]["dataset"][0]["technical_resource"][0]["faire"]["site"]
    assert list(validator("faire-profile-1.json").iter_errors(doc))
