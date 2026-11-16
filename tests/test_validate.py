import copy
import json
from pathlib import Path

import pytest

from faire import filters, validate

DATA = Path(__file__).parent / "data"


def doc(name="federated.json"):
    return json.loads((DATA / name).read_text())


def ds(d, ident):
    return next(x for x in d["dmp"]["dataset"] if x["dataset_id"]["identifier"] == ident)


def messages(d):
    return [str(v) for v in validate.validate(d)]


@pytest.mark.parametrize("name", ["single_site.json", "federated.json"])
def test_valid_examples_have_no_violations(name):
    assert validate.validate(doc(name)) == []


def mut_duplicate_id(d):
    ds(d, "atlas")["dataset_id"]["identifier"] = "dicoms"


def mut_unpinned_template(d):
    ds(d, "analysis")["faire"]["template"]["version"] = "main"


def mut_unresolved_source(d):
    ds(d, "analysis")["related_identifier"].append(
        {"identifier": "ghost", "type": "other", "relation_type": "IsDerivedFrom"}
    )


def mut_cycle(d):
    ds(d, "dicoms")["related_identifier"] = [
        {"identifier": "analysis", "type": "other", "relation_type": "IsDerivedFrom"}
    ]
    ds(d, "dicoms")["technical_resource"] = []


def mut_only_resources(d):
    ds(d, "analysis")["faire"]["sources"]["standardized"] = {"role": "resource"}


def mut_no_license(d):
    for dist in ds(d, "atlas")["distribution"]:
        dist.pop("license", None)


def mut_free_text_license(d):
    ds(d, "atlas")["distribution"][0]["license"][0]["license_ref"] = "CC BY 4.0"


def mut_release_without_license(d):
    del ds(d, "standardized")["distribution"][1]["license"]


def mut_ordinary_archival_host(d):
    ds(d, "standardized")["distribution"][2]["host"]["faire"]["long_term"] = False
    del ds(d, "standardized")["distribution"][2]["host"]["certified_with"]


def mut_bad_filter(d):
    ds(d, "standardized")["distribution"][0]["faire"]["filter"] = "not (metadata=a=b"


def mut_inline_secret(d):
    ds(d, "standardized")["distribution"][1]["host"]["faire"]["secrets"]["token"] = "abc123 xyz!"


def mut_credential_parameter(d):
    ds(d, "standardized")["distribution"][1]["host"]["faire"]["parameters"]["password"] = "x"


def mut_two_way_elsewhere(d):
    ds(d, "standardized")["distribution"][1]["faire"]["two_way"] = True


def mut_hub_without_coordinator(d):
    del d["dmp"]["faire"]["coordinator"]


def mut_instrument_without_site(d):
    del ds(d, "dicoms")["technical_resource"][0]["faire"]["site"]


def mut_instrument_duplicate(d):
    ds(d, "dicoms")["technical_resource"].append(
        copy.deepcopy(ds(d, "dicoms")["technical_resource"][0])
    )


def mut_instrument_two_sites(d):
    other = copy.deepcopy(ds(d, "dicoms"))
    other["dataset_id"]["identifier"] = "mri_raw"
    other["technical_resource"] = [
        {"name": "Prisma", "faire": {"instrument_id": "PrismaFit16001", "site": "b"}}
    ]
    d["dmp"]["dataset"].append(other)


def mut_instrument_release(d):
    ds(d, "dicoms")["distribution"].append(
        {
            "title": "Pub",
            "data_access": "open",
            "license": [{"license_ref": "https://x.org/l", "start_date": "2026-01-01"}],
            "faire": {"stage": "release"},
        }
    )


def mut_instrument_derived(d):
    ds(d, "dicoms")["related_identifier"] = [
        {"identifier": "atlas", "type": "other", "relation_type": "IsDerivedFrom"}
    ]


CASES = [
    (mut_duplicate_id, "duplicate dataset identifier"),
    (mut_unpinned_template, "not pinned"),
    (mut_unresolved_source, "matches no dataset"),
    (mut_cycle, "provenance cycle"),
    (mut_only_resources, "resource-only"),
    (mut_no_license, "no distribution declares a license"),
    (mut_free_text_license, "not a resolvable identifier"),
    (mut_release_without_license, "release distribution declares no license"),
    (mut_ordinary_archival_host, "not declared long-term"),
    (mut_bad_filter, "cannot be parsed"),
    (mut_inline_secret, "holds a value instead of a secret name"),
    (mut_credential_parameter, "looks like a credential"),
    (mut_two_way_elsewhere, "must target the declared hub"),
    (mut_hub_without_coordinator, "without a coordinator"),
    (mut_instrument_without_site, "no site"),
    (mut_instrument_duplicate, "declared twice"),
    (mut_instrument_two_sites, "declared at site"),
    (mut_instrument_release, "cannot have a distribution to the hub or at stage release"),
    (mut_instrument_derived, "must be a root dataset"),
]


@pytest.mark.parametrize(("mutate", "expected"), CASES, ids=[c[0].__name__ for c in CASES])
def test_failing_fixture_per_check(mutate, expected):
    d = doc()
    mutate(d)
    assert any(expected in m for m in messages(d)), messages(d)


def test_missing_base_field_reports_location():
    d = doc()
    del d["dmp"]["title"]
    found = [v for v in validate.validate(d) if "title" in v.message]
    assert found and found[0].location == "/dmp"


def test_missing_sample_entities_fails():
    d = doc()
    del d["dmp"]["faire"]["sample_entities"]
    assert any("sample_entities" in m for m in messages(d))


def test_stripping_extension_leaves_valid_base_document():
    import jsonschema

    schema = json.loads(
        (Path(validate.__file__).parent / "schema" / "maDMP-schema-1.3.json").read_text()
    )

    def strip(o):
        if isinstance(o, dict):
            return {k: strip(v) for k, v in o.items() if k != "faire"}
        if isinstance(o, list):
            return [strip(v) for v in o]
        return o

    for name in ["single_site.json", "federated.json"]:
        jsonschema.validate(strip(doc(name)), schema)


@pytest.mark.parametrize(
    "expr",
    [
        "anything",
        "not metadata=distribution-restrictions=sensitive",
        "include=*.nii.gz and not exclude=*/pilot/*",
        "(include=a/* or include=b/*) and metadata=tag=done",
        "metadata=pagecount>=100 and metadata=pagecount<=200",
    ],
)
def test_filter_accepts_annex_expressions(expr):
    filters.parse(expr)


@pytest.mark.parametrize(
    "expr", ["", "and", "not", "include=", "(anything", "anything)", "foo=bar", "anything anything"]
)
def test_filter_rejects_malformed(expr):
    with pytest.raises(filters.FilterError):
        filters.parse(expr)
