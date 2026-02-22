from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

import requests


@dataclass(frozen=True)
class Submission:
    title: str
    description: str
    track: str
    team_members: list[str]
    repo_urls: list[str]
    submitted_at: str | None
    source: str


def load_submissions(source: Path | str) -> list[Submission]:
    source_str = str(source).strip()
    if _looks_like_url(source_str):
        return [_load_submission_from_url(source_str)]

    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"Submission source not found: {path}")
    if path.suffix.lower() != ".csv":
        raise ValueError(f"Unsupported submission source for {path}; expected .csv or URL")

    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)

    return [_row_to_submission(row, str(path), idx) for idx, row in enumerate(rows, start=1)]


def _row_to_submission(row: dict[str, str], source: str, idx: int) -> Submission:
    if not isinstance(row, dict):
        raise ValueError(f"Invalid CSV row at {source}:{idx}; expected mapping")

    title = _first_non_empty(
        row,
        "project title",
        "title",
        "project",
        "submission title",
    )
    description = _first_non_empty(row, "about the project", "description", "summary")
    track = _first_non_empty(
        row,
        "selected track",
        "track",
        "opt-in prizes",
        "prize category",
    )
    submitted_at = _first_non_empty(
        row,
        "submitted at",
        "submission timestamp",
        "project created at",
        "created at",
    )

    member_blob = _join_non_empty(
        _first_non_empty(
            row,
            "team members",
            "project members",
            "member names",
            "participants",
        ),
        _first_non_empty(
            row,
            "team member emails",
            "participant emails",
            "participants email",
        ),
    )
    team_members = _split_list_field(member_blob)

    repo_blob = _join_non_empty(
        _first_non_empty(
            row,
            "try it out links",
            "try it out",
            "repository",
            "repo url",
            "code url",
            "github",
            "gitlab",
        ),
        _first_non_empty(row, "project url", "submission url"),
    )
    repo_urls = _extract_repo_urls(repo_blob)

    return Submission(
        title=title or "(untitled submission)",
        description=description,
        track=track,
        team_members=team_members,
        repo_urls=repo_urls,
        submitted_at=submitted_at or None,
        source=source,
    )


def _first_non_empty(row: dict[str, str], *candidates: str) -> str:
    normalized = {_normalize_key(k): (v or "").strip() for k, v in row.items()}
    for key in candidates:
        value = normalized.get(_normalize_key(key), "")
        if value:
            return value
    return ""


def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _split_list_field(value: str) -> list[str]:
    if not value:
        return []
    items = [p.strip() for p in re.split(r"[;\n|,]+", value)]
    deduped: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not item:
            continue
        lowered = item.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(item)
    return deduped


def _join_non_empty(*values: str) -> str:
    return "\n".join([v for v in values if v])


def _extract_repo_urls(value: str) -> list[str]:
    urls = _extract_urls(value)
    repos: list[str] = []
    seen: set[str] = set()

    for url in urls:
        host = urlparse(url).netloc.lower()
        if not host:
            continue
        if "github.com" not in host and "gitlab" not in host:
            continue
        if url in seen:
            continue
        seen.add(url)
        repos.append(url)

    return repos


def _extract_urls(value: str) -> list[str]:
    if not value:
        return []
    return [m.group(0).rstrip(").,;") for m in re.finditer(r"https?://[^\s\"'<>]+", value)]


def _looks_like_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _load_submission_from_url(url: str) -> Submission:
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    html = response.text

    title = _extract_meta_content(html, "property", "og:title") or _extract_title_tag(html)
    description = _extract_meta_content(html, "name", "description") or ""
    track = _extract_submitted_to_text(html)
    team_members = _extract_team_members(html)
    repo_urls = _extract_repo_urls_from_html(html)
    submitted_at = _extract_datetime_value(html)

    return Submission(
        title=title or "(untitled submission)",
        description=description,
        track=track,
        team_members=team_members,
        repo_urls=repo_urls,
        submitted_at=submitted_at,
        source=url,
    )


def _extract_meta_content(html: str, attr_name: str, attr_value: str) -> str:
    pattern = (
        rf"<meta[^>]+{attr_name}\s*=\s*[\"']{re.escape(attr_value)}[\"'][^>]*content\s*=\s*[\"']([^\"']*)[\"']"
    )
    match = re.search(pattern, html, flags=re.IGNORECASE)
    return unescape(match.group(1)).strip() if match else ""


def _extract_title_tag(html: str) -> str:
    match = re.search(r"<title>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return _clean_text(match.group(1))


def _extract_submitted_to_text(html: str) -> str:
    anchor = re.search(
        r"<div id=\"submissions\"[^>]*>[\s\S]{0,2000}?<a [^>]*>([^<]+)</a>",
        html,
        flags=re.IGNORECASE,
    )
    if not anchor:
        return ""
    return _clean_text(anchor.group(1))


def _extract_team_members(html: str) -> list[str]:
    section = _extract_section(html, r"<section id=\"app-team\".*?</section>")
    if not section:
        return []

    names = re.findall(
        r"<a class=\"user-profile-link\"[^>]*>([^<]+)</a>",
        section,
        flags=re.IGNORECASE,
    )
    return _dedupe([_clean_text(name) for name in names if _clean_text(name)])


def _extract_repo_urls_from_html(html: str) -> list[str]:
    nav = _extract_section(html, r"<ul data-role=\"software-urls\".*?</ul>")
    if not nav:
        return []
    return _extract_repo_urls(" ".join(_extract_urls(nav)))


def _extract_datetime_value(html: str) -> str | None:
    match = re.search(r"<time[^>]+datetime=\"([^\"]+)\"", html, flags=re.IGNORECASE)
    if not match:
        return None
    value = _clean_text(match.group(1))
    return value or None


def _extract_section(html: str, pattern: str) -> str:
    match = re.search(pattern, html, flags=re.IGNORECASE | re.DOTALL)
    return match.group(0) if match else ""


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value)).strip()


def _dedupe(items: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result
