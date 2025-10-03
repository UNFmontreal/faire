import pathlib
import datalad.support
from typing import List
from .base import GitHostingInterface


# a bare file-based storage, mainly for testing
class BareBackend(GitHostingInterface):

    def __init__(self):
        pass

    def create_repo(self, path: pathlib.Path, exists_ok: bool = False) -> None:
        pass

    def trigger(self) -> None:
        pass

    def open_pr(self,
        repo_path: pathlib.Path,
        source_branch:str,
        target_branch:str,
        title: str,
        description: str,
        labels: List[str]=[],
    ) -> None:
        pass
