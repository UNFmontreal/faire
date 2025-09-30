import gitlab
import pathlib
import logging
from typing import List
from .base import GitHostingInterface

class GitlabBackend(GitHostingInterface):

    def __init__(self):

        self._connect()

    def _connect(
        self, debug: bool = False
    ) -> None:
        """
        Connection to Gitlab
        """
        self._gl = gitlab.Gitlab(gitlab_url.geturl(), private_token=GITLAB_TOKEN)
        if debug:
            self._gl.enable_debug()
        self._gl.auth()

    def create_repo(self, path: pathlib.Path, exists_ok: bool = False):
        return self._get_or_create_gitlab_group(path, exists_ok=True)

    def _get_or_create_gitlab_group(self, path: pathlib.Path, exists_ok: bool = False):

        """fetch or create a gitlab repo"""
        project_name = project_path.parts

        # Look for exact repo/project:
        p = gl.projects.list(search=project_name[-1])
        if p:
            for curr_p in p:
                if curr_p.path_with_namespace == str(project_path):
                    return curr_p

        g = self._get_or_create_gitlab_group(gl, project_path.parent)
        logging.debug(f"Creating project {project_name[-1]} from {g.name}")
        p = gl.projects.create({"name": project_name[-1], "namespace_id": g.id})
        return p

    def _get_or_create_gitlab_group(
        self,
        group_path: pathlib.Path,
    ):
        """fetch or create a gitlab group"""
        group_list = group_path.parts
        found = False
        for keep_groups in reversed(range(len(group_list) + 1)):
            tmp_repo_path = "/".join(group_list[0:keep_groups])
            logging.debug(tmp_repo_path)
            gs = self._gl.groups.list(search=tmp_repo_path)
            for g in gs:
                if g.full_path == tmp_repo_path:
                    found = True
                    break
            if found:
                break
        for nb_groups in range(keep_groups, len(group_list)):
            if nb_groups == 0:
                logging.debug(f"Creating group {group_list[nb_groups]}")
                g = self._gl.groups.create(
                    {"name": group_list[nb_groups], "path": group_list[nb_groups]}
                )
            else:
                logging.debug(f"Creating group {group_list[nb_groups]} from {g.name}")
                g = self._gl.groups.create(
                    {
                        "name": group_list[nb_groups],
                        "path": group_list[nb_groups],
                        "parent_id": g.id,
                    }
                )

        return g


    def open_pr(
        self,
        repo_path: pathlib.Path,
        source_branch:str,
        target_branch:str,
        title: str,
        description: str,
        labels: List[str]=[],
    ) -> None:
        project = _get_or_create_gitlab_group(repo_path)
        mr = project.mergerequests.create({
            'source_branch': source_branch,
            'target_branch': target_branch,
            'title': title,
            'description': description,
            'labels': labels,
        })
