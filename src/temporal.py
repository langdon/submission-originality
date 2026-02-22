from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from src.config import HackathonWindow
from src.models import Commit, IngestResult

Period = Literal["pre", "in", "post"]
RiskFlag = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class TemporalReport:
    team: str
    repo_url: str
    total_commits: int
    pre_window: int
    in_window: int
    post_window: int
    pre_window_pct: float
    largest_pre_commit: Commit | None
    first_in_window_commit: Commit | None
    risk_flag: RiskFlag
    risk_reason: str


def classify_commit(commit: Commit, window: HackathonWindow) -> Period:
    start_dt, end_dt = parse_hackathon_window(window)
    commit_dt = _parse_datetime(commit.timestamp).astimezone(start_dt.tzinfo)

    if commit_dt < start_dt:
        return "pre"
    if commit_dt > end_dt:
        return "post"
    return "in"


def analyze_repo(result: IngestResult, window: HackathonWindow) -> TemporalReport:
    start_dt, end_dt = parse_hackathon_window(window)

    pre_commits: list[Commit] = []
    in_commits: list[Commit] = []
    post_commits: list[Commit] = []

    for commit in result.commits:
        commit_dt = _parse_datetime(commit.timestamp).astimezone(start_dt.tzinfo)
        if commit_dt < start_dt:
            pre_commits.append(commit)
        elif commit_dt > end_dt:
            post_commits.append(commit)
        else:
            in_commits.append(commit)

    total_commits = len(result.commits)
    pre_window = len(pre_commits)
    in_window = len(in_commits)
    post_window = len(post_commits)
    pre_window_pct = (pre_window / total_commits * 100.0) if total_commits else 0.0

    largest_pre_commit = (
        max(pre_commits, key=lambda commit: len(commit.files_changed)) if pre_commits else None
    )
    first_in_window_commit = (
        min(in_commits, key=lambda commit: _parse_datetime(commit.timestamp))
        if in_commits
        else None
    )

    risk_flag, risk_reason = _derive_risk(pre_window_pct, largest_pre_commit, total_commits)

    return TemporalReport(
        team=result.spec.team,
        repo_url=result.spec.repo_url,
        total_commits=total_commits,
        pre_window=pre_window,
        in_window=in_window,
        post_window=post_window,
        pre_window_pct=pre_window_pct,
        largest_pre_commit=largest_pre_commit,
        first_in_window_commit=first_in_window_commit,
        risk_flag=risk_flag,
        risk_reason=risk_reason,
    )


def parse_hackathon_window(window: HackathonWindow) -> tuple[datetime, datetime]:
    tz = ZoneInfo(window.timezone)
    start_dt = _parse_datetime(window.start_datetime, default_tz=tz).astimezone(tz)
    end_dt = _parse_datetime(window.end_datetime, default_tz=tz).astimezone(tz)
    if end_dt < start_dt:
        raise ValueError("Hackathon window end_datetime must be after start_datetime")
    return start_dt, end_dt


def _parse_datetime(raw_value: str, default_tz: ZoneInfo | None = None) -> datetime:
    dt = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        tz = default_tz or timezone.utc
        return dt.replace(tzinfo=tz)
    return dt


def _derive_risk(
    pre_window_pct: float,
    largest_pre_commit: Commit | None,
    total_commits: int,
) -> tuple[RiskFlag, str]:
    if total_commits == 0:
        return "low", "No commits found; temporal originality risk is low."

    largest_pre_size = len(largest_pre_commit.files_changed) if largest_pre_commit else 0

    if pre_window_pct > 50.0:
        return "high", f"{pre_window_pct:.1f}% of commits were made before the hackathon window."
    if largest_pre_size > 20:
        return (
            "high",
            f"Largest pre-window commit touched {largest_pre_size} files (>20).",
        )
    if pre_window_pct > 20.0:
        return (
            "medium",
            f"{pre_window_pct:.1f}% of commits were made before the hackathon window (>20%).",
        )
    if largest_pre_size > 10:
        return (
            "medium",
            f"Largest pre-window commit touched {largest_pre_size} files (>10).",
        )
    return "low", "Most commits were made during the hackathon window."
