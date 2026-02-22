from __future__ import annotations

import requests

from src.ingest import ingest_repo, parse_repo_url
from src.models import RepoSpec


class FakeResponse:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class SequenceSession:
    def __init__(self, responses):
        self._responses = list(responses)

    def get(self, url, headers=None, params=None, timeout=30):
        if not self._responses:
            raise AssertionError(f"No fake response available for URL {url}")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_parse_github_url() -> None:
    parsed = parse_repo_url("https://github.com/octocat/hello-world.git")

    assert parsed.provider == "github"
    assert parsed.owner == "octocat"
    assert parsed.repo == "hello-world"


def test_parse_gitlab_url() -> None:
    parsed = parse_repo_url("https://gitlab.com/group/subgroup/project")

    assert parsed.provider == "gitlab"
    assert parsed.namespace == "group/subgroup"
    assert parsed.repo == "project"


def test_unreachable_repo_collects_error() -> None:
    session = SequenceSession([requests.RequestException("boom")])
    spec = RepoSpec(team="Team A", repo_url="https://github.com/org/repo")

    result = ingest_repo(spec, github_token="token", session=session)

    assert result.errors
    assert "GitHub request failed" in result.errors[0]


def test_missing_token_private_repo_warns_and_skips() -> None:
    session = SequenceSession([FakeResponse(401, {"message": "Requires authentication"})])
    spec = RepoSpec(team="Team A", repo_url="https://gitlab.com/group/repo")

    result = ingest_repo(spec, gitlab_token=None, session=session)

    assert not result.commits
    assert result.warnings
    assert "missing token" in result.warnings[0].lower()
