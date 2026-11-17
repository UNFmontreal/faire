import pytest

from faire import rules


def test_pattern_resolution_substitutes_only_the_samples_values():
    sample = {"subject": "01", "session": "003"}
    assert rules.resolve("sub-{subject}/ses-{session}/*.nii", sample) == "sub-01/ses-003/*.nii"


def test_datalad_placeholders_are_left_alone():
    assert rules.resolve("cat {inputs} > {outputs}", {}) == "cat {inputs} > {outputs}"


def test_missing_entity_is_named():
    with pytest.raises(rules.MissingEntity, match="session"):
        rules.resolve("{subject}/{session}/x", {"subject": "01"})


def test_matcher_captures_entities_and_only_those_values_match():
    m = rules.matcher("sourcedata/src/{subject}/{session}/*.txt")
    hit = m.match("sourcedata/src/01/003/a.txt")
    assert hit.groupdict() == {"subject": "01", "session": "003"}
    assert m.match("sourcedata/src/01/003/sub/a.txt") is None
    assert m.match("sourcedata/src/01/003/a.nii") is None


def test_glob_match_of_a_resolved_pattern():
    assert rules.glob_match("sourcedata/src/01/*.txt", "sourcedata/src/01/a.txt")
    assert not rules.glob_match("sourcedata/src/01/*.txt", "sourcedata/src/02/a.txt")
    assert rules.glob_match(".faire/logs/", ".faire/logs/x.log")


def parse(**rule):
    base = {
        "id": "r",
        "trigger": {"source": "src"},
        "container": "tool",
        "command": "true",
        "inputs": ["sourcedata/src/{subject}/x"],
    }
    return rules.parse({"rules": [base | rule]})


def test_rule_fields_and_defaults():
    rule = parse(inputs=[{"pattern": "sourcedata/src/{subject}/x", "required": True}]).rules[0]
    assert rule.inputs[0].required and rule.entities() == ["subject"]
    assert not rule.trigger.content and rule.optional is False


@pytest.mark.parametrize(
    "bad",
    [{"trigger": {}}, {"trigger": {"source": "a", "paths": ["b"]}}, {"container": ""}, {"id": ""}],
)
def test_invalid_rules_are_rejected(bad):
    with pytest.raises(rules.RuleError):
        parse(**bad)


def test_unknown_container_names_rule_and_container():
    rs = parse(container="nope")
    with pytest.raises(rules.RuleError, match="'r'.*'nope'"):
        rules.check_containers(rs, {"tool"})
