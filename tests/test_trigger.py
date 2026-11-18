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


class FlakyPlatform(FakePlatform):
    """The first pipeline start is lost."""

    def __init__(self, root):
        super().__init__(root)
        self.failures = 1

    def trigger_pipeline(self, repo, ref, variables):
        if self.failures:
            self.failures -= 1
            raise PlatformError("connection reset")
        return super().trigger_pipeline(repo, ref, variables)


def test_lost_trigger_is_recovered_because_planning_works_from_state(tmp_path):
    from datalad.api import Dataset

    from rulefix import add_samples, make_derived, write_source
    from test_planning import current_digests, plan, record

    src = write_source(tmp_path / "src", {"01/a.txt": "one\n", "02/a.txt": "two\n"})
    ds = make_derived(tmp_path, src)
    for task, digest in current_digests(ds).items():
        record(ds, task, digest)
    assert plan(ds).empty

    add_samples(src, {"03/a.txt": "three\n"})  # the upstream accepts a new sample...
    platform = FlakyPlatform(tmp_path / "hosting")
    group = platform.ensure_group("g")
    platform.ensure_repository(group.path, "derived")
    with pytest.raises(PlatformError, match="connection reset"):  # ...and its trigger is lost
        trigger.trigger_downstream(platform, ["g/derived"], "src", "abc", "03")
    assert not platform.pipelines

    # nothing was lost: whoever starts the downstream planning pipeline later gets the task
    assert [t.id for t in plan(ds, update=True).tasks] == ["process:subject=03"]
    # and starting it again by the portable trigger works
    trigger.trigger_downstream(platform, ["g/derived"], "src", "abc", "03")
    assert [p[0] for p in platform.pipelines] == ["g/derived"]
    assert Dataset(ds.path).is_installed()
