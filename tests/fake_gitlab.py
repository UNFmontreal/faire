"""A small in-process GitLab REST API, plugged under python-gitlab as a requests adapter.

Only the endpoints faire uses. Responses follow the shapes python-gitlab expects.
"""

import json
import re
from urllib.parse import parse_qs, unquote, urlparse

import requests
from requests.adapters import BaseAdapter


class FakeGitLab(BaseAdapter):
    def __init__(self, approvals_available=True):
        super().__init__()
        self.approvals_available = approvals_available
        self.groups = {}  # full_path -> dict
        self.group_variables = {}  # full_path -> {key: dict}
        self.projects = {}  # id -> dict
        self.next_id = 1
        self.calls = []

    # -- plumbing ---------------------------------------------------------------------------

    def close(self):
        pass

    def _id(self):
        self.next_id += 1
        return self.next_id

    def _response(self, request, status, body=None):
        response = requests.Response()
        response.status_code = status
        response.headers["Content-Type"] = "application/json"
        response._content = json.dumps(body if body is not None else {}).encode()
        response.url = request.url
        response.request = request
        return response

    def send(self, request, **kwargs):
        parsed = urlparse(request.url)
        path = parsed.path.split("/api/v4", 1)[1]
        query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        body = json.loads(request.body) if request.body else {}
        self.calls.append((request.method, path))
        handler = self._route(request.method, path)
        if handler is None:
            return self._response(request, 404, {"message": f"404 not routed {path}"})
        status, data = handler(body, query)
        return self._response(request, status, data)

    # -- routing ----------------------------------------------------------------------------

    def _project_by(self, key):
        key = unquote(key)
        for project in self.projects.values():
            if str(project["id"]) == key or project["path_with_namespace"] == key:
                return project
        return None

    def _route(self, method, path):  # noqa: C901
        m = re.fullmatch(r"/groups/([^/]+)/variables", path)
        if m and method == "GET":

            def listing(b, q):
                key = unquote(m.group(1))
                group = self.groups.get(key) or next(
                    (g for g in self.groups.values() if str(g["id"]) == key), None
                )
                if group is None:
                    return 404, {"message": "404"}
                return 200, list(self.group_variables.get(group["full_path"], {}).values())

            return listing
        m = re.fullmatch(r"/groups/([^/]+)", path)
        if m and method == "GET":
            return lambda b, q: self._get_group(unquote(m.group(1)))
        if path == "/groups" and method == "POST":
            return lambda b, q: self._create_group(b)
        if path == "/projects" and method == "POST":
            return lambda b, q: self._create_project(b)
        m = re.fullmatch(r"/projects/([^/]+)", path)
        if m and method == "GET":
            return lambda b, q: self._get_project(m.group(1))
        if m and method == "PUT":
            return lambda b, q: self._update_project(m.group(1), b)
        m = re.fullmatch(r"/projects/([^/]+)/(.+)", path)
        if m:
            project = self._project_by(m.group(1))
            if project is None:
                return lambda b, q: (404, {"message": "404 Project Not Found"})
            return self._project_route(project, method, m.group(2))
        return None

    def _get_group(self, full_path):
        group = self.groups.get(full_path) or next(
            (g for g in self.groups.values() if str(g["id"]) == full_path), None
        )
        return (200, group) if group else (404, {"message": "404 Group Not Found"})

    def _create_group(self, body):
        parent = next((g for g in self.groups.values() if g["id"] == body.get("parent_id")), None)
        full = f"{parent['full_path']}/{body['path']}" if parent else body["path"]
        group = {"id": self._id(), "name": body["name"], "path": body["path"], "full_path": full}
        self.groups[full] = group
        return 201, group

    def _create_project(self, body):
        group = next((g for g in self.groups.values() if g["id"] == body["namespace_id"]), None)
        full = f"{group['full_path']}/{body['path']}"
        project = {
            "id": self._id(),
            "name": body["name"],
            "path": body["path"],
            "path_with_namespace": full,
            "http_url_to_repo": f"https://gitlab.test/{full}.git",
            "web_url": f"https://gitlab.test/{full}",
            "branches": {},
            "tags": {},
            "variables": {},
            "mrs": [],
            "approval_rules": [],
            "pipelines": [],
        }
        self.projects[project["id"]] = project
        return 201, self._public(project)

    @staticmethod
    def _public(project):
        return {
            k: v
            for k, v in project.items()
            if k in ("id", "name", "path", "path_with_namespace", "http_url_to_repo", "web_url")
        }

    def _update_project(self, key, body):
        project = self._project_by(key)
        if project is None:
            return 404, {"message": "404 Not Found"}
        project.setdefault("settings", {}).update(body)
        return 200, self._public(project)

    def _get_project(self, key):
        project = self._project_by(key)
        return (200, self._public(project)) if project else (404, {"message": "404 Not Found"})

    def _project_route(self, p, method, rest):  # noqa: C901
        m = re.fullmatch(r"protected_branches(?:/(.+))?", rest)
        if m:
            name = unquote(m.group(1)) if m.group(1) else None
            if method == "GET" and name:
                hit = p["branches"].get(name)
                return lambda b, q: (200, hit) if hit else (404, {"message": "404"})
            if method == "DELETE" and name:
                return lambda b, q: (p["branches"].pop(name, None) and (204, {})) or (404, {})
            if method == "POST":

                def create(b, q):
                    p["branches"][b["name"]] = {"id": self._id(), **b}
                    return 201, p["branches"][b["name"]]

                return create
        m = re.fullmatch(r"protected_tags(?:/(.+))?", rest)
        if m:
            name = unquote(m.group(1)) if m.group(1) else None
            if method == "GET" and name:
                hit = p["tags"].get(name)
                return lambda b, q: (200, hit) if hit else (404, {"message": "404"})
            if method == "DELETE" and name:
                return lambda b, q: (p["tags"].pop(name, None) and (204, {})) or (404, {})
            if method == "POST":

                def create(b, q):
                    p["tags"][b["name"]] = {"id": self._id(), **b}
                    return 201, p["tags"][b["name"]]

                return create
        if rest == "approval_rules":
            if not self.approvals_available:
                return lambda b, q: (403, {"message": "403 Forbidden"})
            if method == "GET":
                return lambda b, q: (200, p["approval_rules"])
            if method == "POST":

                def create(b, q):
                    rule = {"id": self._id(), **b}
                    p["approval_rules"].append(rule)
                    return 201, rule

                return create
        m = re.fullmatch(r"variables(?:/(.+))?", rest)
        if m:
            key = unquote(m.group(1)) if m.group(1) else None
            if method == "GET" and key is None:
                return lambda b, q: (200, list(p["variables"].values()))
            if method == "GET":
                hit = p["variables"].get(key)
                return lambda b, q: (200, hit) if hit else (404, {"message": "404"})
            if method == "POST":

                def create(b, q):
                    p["variables"][b["key"]] = b
                    return 201, b

                return create
            if method == "PUT":

                def update(b, q):
                    p["variables"][key] = {**p["variables"][key], **b}
                    return 200, p["variables"][key]

                return update
        m = re.fullmatch(r"merge_requests(?:/(\d+))?", rest)
        if m:
            if method == "GET":

                def listing(b, q):
                    hits = [
                        mr
                        for mr in p["mrs"]
                        if all(
                            mr.get(k) == v
                            for k, v in q.items()
                            if k in ("state", "source_branch", "target_branch")
                        )
                    ]
                    return 200, hits

                return listing
            if method == "POST":

                def create(b, q):
                    mr = {
                        "iid": len(p["mrs"]) + 1,
                        "state": "opened",
                        "web_url": f"{p['web_url']}/-/merge_requests/{len(p['mrs']) + 1}",
                        **b,
                    }
                    p["mrs"].append(mr)
                    return 201, mr

                return create
            if method == "PUT":

                def update(b, q):
                    mr = next(x for x in p["mrs"] if x["iid"] == int(m.group(1)))
                    mr.update(b)
                    return 200, mr

                return update
        if rest == "pipeline" and method == "POST":

            def create(b, q):
                pipeline = {"id": self._id(), **b}
                p["pipelines"].append(pipeline)
                return 201, pipeline

            return create
        return None
