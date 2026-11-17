from datalad.api import create

from faire import identity


def test_environment_overrides_default():
    assert identity.from_environment({}) == identity.Identity(*identity.DEFAULT)
    env = {identity.ENV_NAME: "bot", identity.ENV_EMAIL: "bot@example.org"}
    assert identity.from_environment(env) == identity.Identity("bot", "bot@example.org")


def test_commit_is_attributed_to_automation_identity(tmp_path):
    ds = create(str(tmp_path / "ds"), result_renderer="disabled")
    bot = identity.Identity("faire bot", "bot@example.org")
    identity.apply(ds, bot)
    (tmp_path / "ds" / "result.txt").write_text("output\n")
    ds.save(message="pipeline result", result_renderer="disabled")
    author = ds.repo.call_git(["log", "-1", "--format=%an <%ae>|%cn <%ce>"]).strip()
    assert author == "faire bot <bot@example.org>|faire bot <bot@example.org>"
