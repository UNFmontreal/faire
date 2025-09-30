import pathlib
from abc import ABC, abstractmethod
from typing import List

class GitHostingInterface(ABC):

    @abstractmethod
    def __init__(self):
        pass

    @abstractmethod
    def create_repo(self, path: pathlib.Path, exists_ok: bool = False) -> None:
        pass

    @abstractmethod
    def trigger(self) -> None:
        pass

    @abstractmethod
    def open_pr(self,
        repo_path: pathlib.Path,
        source_branch:str,
        target_branch:str,
        title: str,
        description: str,
        labels: List[str]=[],
    ) -> None:
        pass
