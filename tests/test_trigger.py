import pytest
from click.testing import CliRunner

from faire import trigger
from faire.cli import main
from faire.platform import PlatformError, UnsupportedOperation, factory
from faire.platform.fake import FakePlatform


@pytest.fixture
def platform(tmp_path):
    p = FakePlatform(tmp_path / "h")
    group = p.ensure_group("g")
    for name in ("analysis", "extra"):
        p.ensure_repository(group.path, name)
    return p


def test_portable_trigger_starts_every_downstream_pipeline(platform):
    ids = trigger.trigger_downstream(platform, ["g/analysis", "g/extra"], "std", "abc123", "s1")
    assert len(ids) == 2
    assert [(path, ref) for path, ref, _ in platform.pipelines] == [
        ("g/analysis", "dev"),
        ("g/extra", "dev"),
    ]
    assert platform.pipelines[0][2] == {
        "FAIRE_UPSTREAM": "std",
        "FAIRE_REVISION": "abc123",
        "FAIRE_SAMPLE": "s1",
    }


def test_trigger_without_sample_sends_only_dataset_and_revision(platform):
    trigger.trigger_downstream(platform, ["g/analysis"], "std", "abc")
    assert set(platform.pipelines[0][2]) == {"FAIRE_UPSTREAM", "FAIRE_REVISION"}


def test_unknown_downstream_repository_fails(platform):
    with pytest.raises(PlatformError, match="g/ghost"):
        trigger.trigger_downstream(platform, ["g/ghost"], "std", "abc")


def test_platform_without_trigger_is_refused_up_front(platform):
    platform.supported = platform.supported - {"trigger_pipeline"}
    with pytest.raises(UnsupportedOperation, match="trigger_pipeline"):
        trigger.trigger_downstream(platform, ["g/analysis"], "std", "abc")
    assert not platform.pipelines


def test_a_lost_trigger_is_recovered_by_triggering_again(platform):
    # the pipeline carries no state: starting it again is the recovery
    trigger.trigger_downstream(platform, ["g/analysis"], "std", "abc")
    trigger.trigger_downstream(platform, ["g/analysis"], "std", "abc")
    assert [p[0] for p in platform.pipelines] == ["g/analysis", "g/analysis"]


def test_trigger_command(platform, monkeypatch):
    monkeypatch.setattr(factory, "connect", lambda name, url, token=None: platform)
    result = CliRunner().invoke(
        main,
        [
            "trigger",
            "--platform-url",
            "https://x",
            "--downstream",
            "g/analysis,g/extra",
            "--upstream",
            "std",
            "--revision",
            "abc",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "g/analysis: pipeline" in result.output and len(platform.pipelines) == 2


def test_connect_requires_a_token(monkeypatch):
    monkeypatch.delenv(factory.TOKEN_ENV, raising=False)
    with pytest.raises(PlatformError, match=factory.TOKEN_ENV):
        factory.connect("gitlab", "https://x")
