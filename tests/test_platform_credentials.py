import os
import subprocess

from faire.platform import credentials

URL = "https://gitlab.example.org/group/repo.git"
SECRET = "glpat-not-a-real-token"


def fill(cwd, url=URL):
    request = f"protocol=https\nhost={urlhost(url)}\n\n"
    return subprocess.run(
        ["git", "credential", "fill"], input=request, cwd=cwd, capture_output=True, text=True
    )


def urlhost(url):
    return url.split("//")[1].split("/")[0]


def test_git_receives_the_token_through_the_helper(tmp_path):
    with credentials.git_auth(URL, SECRET):
        out = fill(tmp_path)
    assert out.returncode == 0
    assert "username=oauth2" in out.stdout and f"password={SECRET}" in out.stdout


def test_environment_is_restored_and_nothing_is_written(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "user.name")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "x")
    before = dict(os.environ)
    with credentials.git_auth(URL, SECRET):
        assert os.environ["GIT_CONFIG_COUNT"] == "3"
        assert os.environ["GIT_CONFIG_KEY_0"] == "user.name"  # existing entries are kept
    assert dict(os.environ) == before
    assert list(tmp_path.iterdir()) == []


def test_only_the_platform_host_gets_the_token(tmp_path):
    with credentials.git_auth(URL, SECRET):
        out = subprocess.run(
            ["git", "credential", "fill"],
            input="protocol=https\nhost=other.example.org\n\n",
            cwd=tmp_path,
            capture_output=True,
            text=True,
            env={**os.environ, "GIT_ASKPASS": "true", "GIT_TERMINAL_PROMPT": "0"},
        )
    assert SECRET not in out.stdout


def test_without_token_nothing_changes():
    before = dict(os.environ)
    with credentials.git_auth(URL, None):
        assert dict(os.environ) == before
