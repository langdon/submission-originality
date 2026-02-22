from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Literal

from src.devpost import Submission
from src.models import IngestResult, RepoSpec
from src.temporal import TemporalReport

if TYPE_CHECKING:
    from src.genai_signals import GenAIReport

Severity = Literal["clean", "review-recommended", "flagged"]


@dataclass(frozen=True)
class TeamReport:
    team: str
    repo_url: str
    devpost_title: str | None
    devpost_track: str | None
    devpost_team_members: list[str]
    temporal: TemporalReport | None
    genai: GenAIReport | None
    overall_flag: Severity
    overall_reason: str


def load_genai_analyzer() -> tuple[Callable[[IngestResult], Any] | None, str | None]:
    try:
        module = import_module("src.genai_signals")
    except ModuleNotFoundError:
        return None, "GenAI module unavailable; skipping GenAI signals section."
    except Exception as exc:  # pragma: no cover - defensive fallback
        return None, f"Unable to load GenAI module; skipping GenAI signals section ({exc})."

    analyze_repo = getattr(module, "analyze_repo", None)
    if not callable(analyze_repo):
        return None, "GenAI module missing analyze_repo; skipping GenAI signals section."

    return analyze_repo, None


def analyze_genai_optional(result: IngestResult) -> tuple[Any | None, str | None]:
    analyzer, warning = load_genai_analyzer()
    if analyzer is None:
        return None, warning

    try:
        return analyzer(result), None
    except Exception as exc:  # pragma: no cover - defensive fallback
        return None, f"GenAI analysis failed for {result.spec.repo_url}; skipped ({exc})"


def build_team_report(
    spec: RepoSpec,
    ingest_result: IngestResult,
    temporal: TemporalReport | None,
    genai: Any | None,
    submission: Submission | None,
) -> TeamReport:
    del ingest_result  # included for pipeline consistency and future enrichment

    has_genai_only = bool(
        genai
        and getattr(genai, "genai_signals", [])
        and not getattr(genai, "human_signals", [])
    )

    if temporal and temporal.risk_flag == "high":
        overall_flag: Severity = "flagged"
        overall_reason = (
            f"Temporal originality risk is high: {temporal.risk_reason} "
            "Recommend organizer review before judging."
        )
    elif (temporal and temporal.risk_flag == "medium") or has_genai_only:
        overall_flag = "review-recommended"
        reason_parts: list[str] = []
        if temporal and temporal.risk_flag == "medium":
            reason_parts.append(f"Temporal originality risk is medium: {temporal.risk_reason}")
        if has_genai_only:
            reason_parts.append(
                "GenAI usage signals were detected with limited human engagement indicators"
            )
        overall_reason = "; ".join(reason_parts) + "."
    else:
        overall_flag = "clean"
        overall_reason = "No major originality concerns were detected from available signals."

    members = submission.team_members if submission else []

    return TeamReport(
        team=spec.team,
        repo_url=spec.repo_url,
        devpost_title=submission.title if submission else None,
        devpost_track=submission.track if submission else None,
        devpost_team_members=members,
        temporal=temporal,
        genai=genai,
        overall_flag=overall_flag,
        overall_reason=overall_reason,
    )


def render_team_report(report: TeamReport) -> str:
    devpost_title = report.devpost_title or "Not provided"
    devpost_track = report.devpost_track or "Not provided"
    members = ", ".join(report.devpost_team_members) if report.devpost_team_members else "Not provided"

    lines = [
        f"# {report.team} - {report.overall_flag.upper()}",
        "",
        f"**Repo:** {report.repo_url}",
        f"**Devpost:** {devpost_title} | Track: {devpost_track}",
        f"**Team members:** {members}",
        "",
        "## Temporal Originality",
    ]

    if report.temporal is None:
        lines.append("Temporal analysis was not available for this repository.")
    else:
        lines.extend(
            [
                f"- Commits analyzed: {report.temporal.total_commits}",
                (
                    "- Commit timing: "
                    f"pre-window={report.temporal.pre_window}, "
                    f"in-window={report.temporal.in_window}, "
                    f"post-window={report.temporal.post_window}"
                ),
                f"- Pre-window percentage: {report.temporal.pre_window_pct:.1f}%",
                f"- Risk flag: {report.temporal.risk_flag}",
                f"- Reason: {report.temporal.risk_reason}",
            ]
        )

    lines.extend(["", "## GenAI Signals"])

    genai_signals = list(getattr(report.genai, "genai_signals", [])) if report.genai else []
    if genai_signals:
        for signal in genai_signals:
            lines.append(f"- {signal.name}: {signal.description}")
    else:
        lines.append("None detected.")

    lines.extend(["", "## Human Engagement"])

    human_signals = list(getattr(report.genai, "human_signals", [])) if report.genai else []
    if human_signals:
        for signal in human_signals:
            lines.append(f"- {signal.name}: {signal.description}")
    else:
        lines.append("None detected.")

    lines.extend(["", "## Summary", report.overall_reason, ""])
    return "\n".join(lines)


def render_index(reports: list[TeamReport]) -> str:
    severity_rank = {"flagged": 0, "review-recommended": 1, "clean": 2}
    ordered = sorted(
        reports,
        key=lambda report: (severity_rank.get(report.overall_flag, 99), report.team.lower()),
    )

    lines = [
        "# Submission Originality Summary",
        "",
        "| Team | Flag | Temporal Risk | Pre-window % | GenAI Signals |",
        "|---|---|---|---:|---:|",
    ]

    for report in ordered:
        temporal_risk = report.temporal.risk_flag if report.temporal else "n/a"
        pre_window_pct = f"{report.temporal.pre_window_pct:.1f}%" if report.temporal else "n/a"
        genai_count = len(getattr(report.genai, "genai_signals", [])) if report.genai else 0
        lines.append(
            "| "
            f"{report.team} | {report.overall_flag} | {temporal_risk} | {pre_window_pct} | {genai_count} "
            "|"
        )

    lines.append("")
    return "\n".join(lines)


def write_reports(output_dir: Path, reports: list[TeamReport]) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for report in reports:
        slug = _slugify(report.team)
        report_path = output_dir / f"{slug}.md"
        report_path.write_text(render_team_report(report), encoding="utf-8")
        written.append(report_path)

    index_path = output_dir / "index.md"
    index_path.write_text(render_index(reports), encoding="utf-8")
    written.append(index_path)

    return written


def _slugify(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in value.strip())
    squashed = "-".join(part for part in cleaned.split("-") if part)
    return squashed or "team-report"
