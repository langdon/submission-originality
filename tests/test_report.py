from __future__ import annotations

from src.devpost import Submission
from src.genai_signals import GenAIReport, GenAISignal
from src.models import Commit, IngestResult, RepoSpec
from src.report import (
    analyze_genai_optional,
    build_team_report,
    load_genai_analyzer,
    render_index,
    render_team_report,
)
from src.temporal import TemporalReport


def _spec(team: str = "Team One", repo_url: str = "https://github.com/org/repo") -> RepoSpec:
    return RepoSpec(team=team, repo_url=repo_url)


def _ingest(spec: RepoSpec | None = None) -> IngestResult:
    return IngestResult(spec=spec or _spec())


def _temporal(
    risk_flag: str,
    reason: str = "temporal reason",
    pre_window_pct: float = 10.0,
) -> TemporalReport:
    return TemporalReport(
        team="Team One",
        repo_url="https://github.com/org/repo",
        total_commits=10,
        pre_window=1,
        in_window=8,
        post_window=1,
        pre_window_pct=pre_window_pct,
        largest_pre_commit=None,
        first_in_window_commit=None,
        risk_flag=risk_flag,
        risk_reason=reason,
    )


def _genai(genai_count: int = 1, human_count: int = 0) -> GenAIReport:
    genai_signals = [
        GenAISignal(name=f"genai_{idx}", description="signal", commits=[f"g{idx}"])
        for idx in range(genai_count)
    ]
    human_signals = [
        GenAISignal(name=f"human_{idx}", description="signal", commits=[f"h{idx}"])
        for idx in range(human_count)
    ]
    return GenAIReport(
        team="Team One",
        repo_url="https://github.com/org/repo",
        genai_signals=genai_signals,
        human_signals=human_signals,
        summary="summary",
    )


def _submission() -> Submission:
    return Submission(
        title="Civic App",
        description="desc",
        track="Community",
        team_members=["Alice", "Bob"],
        repo_urls=["https://github.com/org/repo"],
        submitted_at=None,
        source="https://devpost.com/software/civic-app",
    )


def test_flagged_when_temporal_risk_is_high() -> None:
    report = build_team_report(
        spec=_spec(),
        ingest_result=_ingest(),
        temporal=_temporal("high", reason="60% pre-window"),
        genai=None,
        submission=_submission(),
    )

    assert report.overall_flag == "flagged"
    assert "high" in report.overall_reason.lower()


def test_review_recommended_when_temporal_risk_is_medium() -> None:
    report = build_team_report(
        spec=_spec(),
        ingest_result=_ingest(),
        temporal=_temporal("medium", reason="25% pre-window"),
        genai=None,
        submission=_submission(),
    )

    assert report.overall_flag == "review-recommended"


def test_clean_when_no_signals() -> None:
    report = build_team_report(
        spec=_spec(),
        ingest_result=_ingest(),
        temporal=_temporal("low", reason="mostly in-window"),
        genai=_genai(genai_count=0, human_count=0),
        submission=_submission(),
    )

    assert report.overall_flag == "clean"


def test_render_team_report_includes_expected_sections() -> None:
    team_report = build_team_report(
        spec=_spec(),
        ingest_result=_ingest(),
        temporal=_temporal("medium", reason="25% pre-window"),
        genai=_genai(genai_count=1, human_count=1),
        submission=_submission(),
    )

    markdown = render_team_report(team_report)

    assert "# Team One - REVIEW-RECOMMENDED" in markdown
    assert "## Temporal Originality" in markdown
    assert "## GenAI Signals" in markdown
    assert "## Human Engagement" in markdown
    assert "## Summary" in markdown


def test_render_index_sorts_flagged_first() -> None:
    flagged = build_team_report(
        spec=_spec(team="Zulu"),
        ingest_result=_ingest(),
        temporal=_temporal("high"),
        genai=None,
        submission=None,
    )
    clean = build_team_report(
        spec=_spec(team="Alpha", repo_url="https://github.com/org/alpha"),
        ingest_result=_ingest(_spec(team="Alpha", repo_url="https://github.com/org/alpha")),
        temporal=_temporal("low"),
        genai=None,
        submission=None,
    )

    index_markdown = render_index([clean, flagged])

    lines = [
        line
        for line in index_markdown.splitlines()
        if line.startswith("| ") and "---" not in line and not line.startswith("| Team |")
    ]
    assert lines[0].startswith("| Zulu | flagged")
    assert lines[1].startswith("| Alpha | clean")


def test_missing_devpost_submission_is_handled() -> None:
    report = build_team_report(
        spec=_spec(),
        ingest_result=_ingest(),
        temporal=_temporal("low"),
        genai=None,
        submission=None,
    )

    assert report.devpost_title is None
    assert report.devpost_track is None
    assert report.devpost_team_members == []


def test_missing_genai_module_handled_gracefully(monkeypatch) -> None:
    def fake_import(name: str):
        if name == "src.genai_signals":
            raise ModuleNotFoundError("src.genai_signals")
        raise AssertionError(f"unexpected module request: {name}")

    monkeypatch.setattr("src.report.import_module", fake_import)

    analyzer, warning = load_genai_analyzer()
    assert analyzer is None
    assert warning is not None

    commit = Commit(
        sha="abc",
        author="Alice",
        email="alice@example.com",
        timestamp="2026-02-20T14:00:00Z",
        message="init",
        files_changed=["README.md"],
    )
    result = IngestResult(spec=_spec(), commits=[commit])
    genai_report, warning2 = analyze_genai_optional(result)

    assert genai_report is None
    assert warning2 is not None
