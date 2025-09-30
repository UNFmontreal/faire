import os
from .base import GitHostingInterface
from .gitlab import GitlabBackend
from .github import GithubBackend

ENV2GITHUB = {
    "GITLAB_CI": GitlabBackend,
    "GITHUB_REPOSITORY": GithubBackend,
}

def get_githost() -> GitHostingInterface:
    """
    Instantiate the GitHostingInterface from the config/envvars.
    """
    for k, kls in ENV2GITHUB.items():
        if os.environ.get(k):
            return kls()


DEFAULT_GITHOST = get_githost()
