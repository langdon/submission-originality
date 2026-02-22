from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote, urlparse

import requests

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
    session: requests.Session | None = None,
) -> IngestResult:
    result = IngestResult(spec=spec)

    try:
        parsed = parse_repo_url(spec.repo_url)
    except ValueError as exc:
        result.errors.append(str(exc))
        return result

    if parsed.provider == "unknown":
        result.warnings.append(f"Unsupported host '{parsed.host}' for {spec.repo_url}; skipped")
        return result

    client = session or requests.Session()
    github_token = github_token if github_token is not None else os.getenv("GITHUB_TOKEN")
    gitlab_token = gitlab_token if gitlab_token is not None else os.getenv("GITLAB_TOKEN")

    if parsed.provider == "github":
        _ingest_github(result, parsed, client, github_token)
    elif parsed.provider == "gitlab":
        _ingest_gitlab(result, parsed, client, gitlab_token)

    return result


def _ingest_github(
    result: IngestResult,
    parsed: ParsedRepoURL,
    session: requests.Session,
    token: str | None,
) -> None:
    owner = parsed.owner or ""
    repo = parsed.repo or ""

    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    commits_url = f"https://api.github.com/repos/{owner}/{repo}/commits"
    params = {"per_page": 100}
    page = 1

    while True:
        params["page"] = page
        response = _safe_get(session, commits_url, headers=headers, params=params)
        if response is None:
            result.errors.append(f"GitHub request failed for {result.spec.repo_url}")
            return

        if response.status_code in {401, 403}:
            if token:
                result.errors.append(
                    f"GitHub access denied for {result.spec.repo_url}; token may lack scope"
                )
            else:
                result.warnings.append(
                    f"GitHub repo may be private: {result.spec.repo_url}; missing token, skipped"
                )
            return

        if response.status_code == 404:
            result.errors.append(f"GitHub repo not found or unreachable: {result.spec.repo_url}")
            return

        if response.status_code >= 400:
            result.errors.append(
                f"GitHub API error ({response.status_code}) for {result.spec.repo_url}"
            )
            return

        page_data = response.json()
        if not isinstance(page_data, list) or not page_data:
            break

        for item in page_data:
            sha = str(item.get("sha") or "")
            if not sha:
                continue

            detail_url = f"https://api.github.com/repos/{owner}/{repo}/commits/{sha}"
            detail = _safe_get(session, detail_url, headers=headers)
            if detail is None or detail.status_code >= 400:
                result.warnings.append(
                    f"Failed to fetch commit details for {sha} in {result.spec.repo_url}"
                )
                continue

            detail_data = detail.json()
            commit_obj = detail_data.get("commit") or {}
            author_obj = commit_obj.get("author") or {}
            files = detail_data.get("files") or []

            result.commits.append(
                Commit(
                    sha=sha,
                    author=str(author_obj.get("name") or "unknown"),
                    email=str(author_obj.get("email") or "unknown"),
                    timestamp=_normalize_timestamp(str(author_obj.get("date") or "")),
                    message=str(commit_obj.get("message") or ""),
                    files_changed=[
                        str(file_obj.get("filename"))
                        for file_obj in files
                        if isinstance(file_obj, dict) and file_obj.get("filename")
                    ],
                )
            )

        if len(page_data) < 100:
            break
        page += 1


def _ingest_gitlab(
    result: IngestResult,
    parsed: ParsedRepoURL,
    session: requests.Session,
    token: str | None,
) -> None:
    host = parsed.host
    namespace = parsed.namespace or ""
    repo = parsed.repo or ""
    project_path = f"{namespace}/{repo}" if namespace else repo
    encoded_project = quote(project_path, safe="")

    headers: dict[str, str] = {}
    if token:
        headers["PRIVATE-TOKEN"] = token

    commits_url = f"https://{host}/api/v4/projects/{encoded_project}/repository/commits"
    page = 1
    per_page = 100

    while True:
        response = _safe_get(
            session,
            commits_url,
            headers=headers,
            params={"per_page": per_page, "page": page},
        )
        if response is None:
            result.errors.append(f"GitLab request failed for {result.spec.repo_url}")
            return

        if response.status_code in {401, 403}:
            if token:
                result.errors.append(
                    f"GitLab access denied for {result.spec.repo_url}; token may lack scope"
                )
            else:
                result.warnings.append(
                    f"GitLab repo may be private: {result.spec.repo_url}; missing token, skipped"
                )
            return

        if response.status_code == 404:
            result.errors.append(f"GitLab repo not found or unreachable: {result.spec.repo_url}")
            return

        if response.status_code >= 400:
            result.errors.append(
                f"GitLab API error ({response.status_code}) for {result.spec.repo_url}"
            )
            return

        page_data = response.json()
        if not isinstance(page_data, list) or not page_data:
            break

        for item in page_data:
            sha = str(item.get("id") or "")
            if not sha:
                continue

            detail_url = (
                f"https://{host}/api/v4/projects/{encoded_project}/repository/commits/{sha}"
            )
            detail = _safe_get(session, detail_url, headers=headers)
            if detail is None or detail.status_code >= 400:
                result.warnings.append(
                    f"Failed to fetch commit details for {sha} in {result.spec.repo_url}"
                )
                continue

            diff_url = (
                f"https://{host}/api/v4/projects/{encoded_project}/repository/commits/{sha}/diff"
            )
            diff = _safe_get(session, diff_url, headers=headers)
            if diff is None or diff.status_code >= 400:
                files_changed: list[str] = []
            else:
                diff_data = diff.json()
                files_changed = [
                    str(entry.get("new_path") or entry.get("old_path"))
                    for entry in diff_data
                    if isinstance(entry, dict)
                    and (entry.get("new_path") or entry.get("old_path"))
                ]

            detail_data = detail.json()
            result.commits.append(
                Commit(
                    sha=sha,
                    author=str(detail_data.get("author_name") or "unknown"),
                    email=str(detail_data.get("author_email") or "unknown"),
                    timestamp=_normalize_timestamp(str(detail_data.get("committed_date") or "")),
                    message=str(detail_data.get("message") or ""),
                    files_changed=files_changed,
                )
            )

        if len(page_data) < per_page:
            break
        page += 1


def _safe_get(
    session: requests.Session,
    url: str,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
) -> requests.Response | None:
    try:
        return session.get(url, headers=headers, params=params, timeout=30)
    except requests.RequestException:
        return None


def _normalize_timestamp(raw_value: str) -> str:
    if not raw_value:
        return ""

    try:
        dt = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except ValueError:
        return raw_value
