from __future__ import annotations

from src.config import HackathonWindow
from src.models import Commit, IngestResult, RepoSpec
from src.temporal import analyze_repo, classify_commit


def _commit(sha: str, timestamp: str, files_changed: int = 1) -> Commit:
    return Commit(
        sha=sha,
        author="Test User",
        email="test@example.com",
        timestamp=timestamp,
        message=f"commit {sha}",
        files_changed=[f"file_{i}.py" for i in range(files_changed)],
    )


def _window() -> HackathonWindow:
    return HackathonWindow(
        start_datetime="2026-02-20T09:00:00",
        end_datetime="2026-02-22T17:00:00",
        timezone="America/New_York",
    )


def _ingest(commits: list[Commit]) -> IngestResult:
    return IngestResult(
        spec=RepoSpec(team="Team Test", repo_url="https://github.com/org/repo"),
        commits=commits,
    )


def test_classify_commit_pre_in_post() -> None:
    window = _window()

    pre = _commit("pre", "2026-02-20T13:59:59Z")
    in_window = _commit("in", "2026-02-20T14:00:00Z")
    post = _commit("post", "2026-02-22T22:00:01Z")

    assert classify_commit(pre, window) == "pre"
    assert classify_commit(in_window, window) == "in"
    assert classify_commit(post, window) == "post"


def test_boundary_commit_is_in_window() -> None:
    window = _window()
    at_start = _commit("start", "2026-02-20T14:00:00Z")
    at_end = _commit("end", "2026-02-22T22:00:00Z")

    assert classify_commit(at_start, window) == "in"
    assert classify_commit(at_end, window) == "in"


def test_all_in_window_is_low_risk() -> None:
    commits = [
        _commit("a", "2026-02-20T14:05:00Z"),
        _commit("b", "2026-02-21T12:00:00Z"),
    ]

    report = analyze_repo(_ingest(commits), _window())

    assert report.pre_window == 0
    assert report.in_window == 2
    assert report.post_window == 0
    assert report.pre_window_pct == 0.0
    assert report.risk_flag == "low"


def test_more_than_half_pre_window_is_high_risk() -> None:
    commits = [
        _commit("a", "2026-02-18T12:00:00Z"),
        _commit("b", "2026-02-19T12:00:00Z"),
        _commit("c", "2026-02-20T14:30:00Z"),
    ]

    report = analyze_repo(_ingest(commits), _window())

    assert report.pre_window == 2
    assert report.total_commits == 3
    assert report.pre_window_pct > 50.0
    assert report.risk_flag == "high"


def test_large_single_pre_window_commit_is_high_risk() -> None:
    commits = [
        _commit("a", "2026-02-19T12:00:00Z", files_changed=21),
        _commit("b", "2026-02-20T15:00:00Z", files_changed=1),
        _commit("c", "2026-02-21T15:00:00Z", files_changed=1),
        _commit("d", "2026-02-22T15:00:00Z", files_changed=1),
        _commit("e", "2026-02-22T16:00:00Z", files_changed=1),
    ]

    report = analyze_repo(_ingest(commits), _window())

    assert report.pre_window == 1
    assert report.pre_window_pct <= 50.0
    assert report.largest_pre_commit is not None
    assert len(report.largest_pre_commit.files_changed) == 21
    assert report.risk_flag == "high"


def test_empty_repo_is_low_risk() -> None:
    report = analyze_repo(_ingest([]), _window())

    assert report.total_commits == 0
    assert report.pre_window == 0
    assert report.in_window == 0
    assert report.post_window == 0
    assert report.pre_window_pct == 0.0
    assert report.largest_pre_commit is None
    assert report.first_in_window_commit is None
    assert report.risk_flag == "low"
