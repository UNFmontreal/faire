import logging
from github import Github, Auth
from .base import GitHostingInterface

class GithubBackend(GitHostingInterface):

    def __init__(self):

        self._connect()

    def _connect(self) -> None:
        pass
