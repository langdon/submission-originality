from __future__ import annotations

from types import SimpleNamespace

from src.ingest import ingest_repo, parse_repo_url
from src.models import RepoSpec


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


def test_successful_clone_parses_commits(monkeypatch) -> None:
    calls = []

    def fake_run(cmd, check, capture_output, text):
        calls.append(cmd)
        if cmd[0:3] == ["git", "clone", "--bare"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if cmd[0] == "git" and "log" in cmd:
            output = (
                "abc123\x00Alice\x00alice@example.com\x002026-02-01T10:00:00+00:00\x00Init\n"
                "README.md\n"
                "src/app.py\n\n"
                "def456\x00Bob\x00bob@example.com\x002026-02-02T11:30:00+00:00\x00Update docs\n"
                "docs/guide.md\n"
            )
            return SimpleNamespace(returncode=0, stdout=output, stderr="")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr("src.ingest.subprocess.run", fake_run)

    spec = RepoSpec(team="Team A", repo_url="https://github.com/org/repo")
    result = ingest_repo(spec, github_token="ghp_secret_token")

    assert not result.errors
    assert len(result.commits) == 2
    assert result.commits[0].sha == "abc123"
    assert result.commits[0].files_changed == ["README.md", "src/app.py"]
    assert result.commits[1].message == "Update docs"
    assert result.commits[1].timestamp == "2026-02-02T11:30:00Z"

    clone_cmd = calls[0]
    assert clone_cmd[0:3] == ["git", "clone", "--bare"]
    assert "ghp_secret_token@github.com" in clone_cmd[3]


def test_clone_failure_redacts_token_in_error(monkeypatch) -> None:
    secret = "ghp_super_secret"

    def fake_run(cmd, check, capture_output, text):
        return SimpleNamespace(
            returncode=1,
            stdout="",
            stderr=f"fatal: Authentication failed for 'https://{secret}@github.com/org/repo.git'",
        )

    monkeypatch.setattr("src.ingest.subprocess.run", fake_run)

    spec = RepoSpec(team="Team B", repo_url="https://github.com/org/private-repo")
    result = ingest_repo(spec, github_token=secret)

    assert result.errors
    assert secret not in result.errors[0]
    assert "***" in result.errors[0]


def test_unknown_host_attempts_clone_and_warns_on_failure(monkeypatch) -> None:
    calls = []

    def fake_run(cmd, check, capture_output, text):
        calls.append(cmd)
        return SimpleNamespace(returncode=1, stdout="", stderr="fatal: could not resolve host")

    monkeypatch.setattr("src.ingest.subprocess.run", fake_run)

    spec = RepoSpec(team="Team C", repo_url="https://example.com/org/repo.git")
    result = ingest_repo(spec)

    assert not result.errors
    assert result.warnings
    assert "unknown host" in result.warnings[0].lower()
    assert calls[0][0:3] == ["git", "clone", "--bare"]
    assert calls[0][3] == "https://example.com/org/repo.git"
