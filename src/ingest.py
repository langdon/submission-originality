from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

from src.models import Commit, IngestResult, RepoSpec

GITHUB_HOSTS = {"github.com", "www.github.com"}


@dataclass(frozen=True)
class ParsedRepoURL:
    provider: str
    host: str
    owner: str | None = None
    repo: str | None = None
    namespace: str | None = None


def parse_repo_url(repo_url: str) -> ParsedRepoURL:
    parsed = urlparse(repo_url)
    host = parsed.netloc.lower().strip()
    if not host:
        return ParsedRepoURL(provider="unknown", host="")

    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if host in GITHUB_HOSTS:
        if len(parts) < 2:
            raise ValueError(f"Invalid GitHub URL: {repo_url}")
        owner = parts[0]
        repo = parts[1].removesuffix(".git")
        return ParsedRepoURL(provider="github", host=host, owner=owner, repo=repo)

    if "gitlab" in host:
        if len(parts) < 2:
            raise ValueError(f"Invalid GitLab URL: {repo_url}")
        repo = parts[-1].removesuffix(".git")
        namespace = "/".join(parts[:-1])
        return ParsedRepoURL(
            provider="gitlab",
            host=host,
            namespace=namespace,
            repo=repo,
        )

    return ParsedRepoURL(provider="unknown", host=host)


def ingest_repo(
    spec: RepoSpec,
    github_token: str | None = None,
    gitlab_token: str | None = None,
) -> IngestResult:
    result = IngestResult(spec=spec)

    try:
        parsed = parse_repo_url(spec.repo_url)
    except ValueError as exc:
        result.errors.append(str(exc))
        return result

    github_token = github_token if github_token is not None else os.getenv("GITHUB_TOKEN")
    gitlab_token = gitlab_token if gitlab_token is not None else os.getenv("GITLAB_TOKEN")

    clone_url = spec.repo_url
    active_token: str | None = None
    if parsed.provider == "github":
        active_token = github_token
        if github_token:
            owner = parsed.owner or ""
            repo = parsed.repo or ""
            clone_url = f"https://{github_token}@{parsed.host}/{owner}/{repo}.git"
    elif parsed.provider == "gitlab":
        active_token = gitlab_token
        if gitlab_token:
            namespace = parsed.namespace or ""
            repo = parsed.repo or ""
            path = f"{namespace}/{repo}".strip("/")
            clone_url = f"https://oauth2:{gitlab_token}@{parsed.host}/{path}.git"

    temp_dir = tempfile.mkdtemp(prefix="submission-originality-")
    repo_dir = os.path.join(temp_dir, "repo.git")
    try:
        clone_proc = subprocess.run(
            ["git", "clone", "--bare", clone_url, repo_dir],
            check=False,
            capture_output=True,
            text=True,
        )
        if clone_proc.returncode != 0:
            message = _sanitize_error_message(clone_proc.stderr or clone_proc.stdout, active_token)
            if parsed.provider == "unknown":
                result.warnings.append(
                    f"Unable to clone unknown host repo {spec.repo_url}; skipped ({message})"
                )
                return result

            if not active_token and _looks_like_auth_failure(message):
                result.warnings.append(
                    f"Repo may be private: {spec.repo_url}; missing token, skipped"
                )
                return result

            result.errors.append(f"Failed to clone repo {spec.repo_url}: {message}")
            return result

        log_proc = subprocess.run(
            [
                "git",
                "-C",
                repo_dir,
                "log",
                "--pretty=format:%H%x00%an%x00%ae%x00%aI%x00%s",
                "--name-only",
                "--no-merges",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if log_proc.returncode != 0:
            message = _sanitize_error_message(log_proc.stderr or log_proc.stdout, active_token)
            result.errors.append(f"Failed to read commit history for {spec.repo_url}: {message}")
            return result

        result.commits = _parse_git_log_output(log_proc.stdout)
        return result
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _parse_git_log_output(output: str) -> list[Commit]:
    commits: list[Commit] = []
    for block in output.split("\n\n"):
        block = block.strip("\n")
        if not block:
            continue
        lines = block.splitlines()
        header = lines[0]
        parts = header.split("\x00")
        if len(parts) != 5:
            continue
        sha, author, email, timestamp, message = parts
        files_changed = [line.strip() for line in lines[1:] if line.strip()]
        commits.append(
            Commit(
                sha=sha,
                author=author,
                email=email,
                timestamp=_normalize_timestamp(timestamp),
                message=message,
                files_changed=files_changed,
            )
        )
    return commits


def _looks_like_auth_failure(message: str) -> bool:
    text = message.lower()
    markers = ["authentication failed", "could not read username", "access denied", "unauthorized"]
    return any(marker in text for marker in markers)


def _sanitize_error_message(message: str, token: str | None) -> str:
    cleaned = " ".join(message.strip().split()) if message else "unknown error"
    if token:
        cleaned = cleaned.replace(token, "***")
    return cleaned


def _normalize_timestamp(raw_value: str) -> str:
    if not raw_value:
        return ""

    try:
        dt = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except ValueError:
        return raw_value
