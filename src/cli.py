from __future__ import annotations

import argparse
from pathlib import Path

from src.config import load_app_config, load_repo_specs
from src.devpost import load_submissions
from src.ingest import ingest_repo
from src.report import analyze_genai_optional, build_team_report, write_reports
from src.temporal import analyze_repo


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest submission repos across hosts")
    parser.add_argument("--input", required=True, help="CSV or YAML submissions file")
    parser.add_argument("--config", required=True, help="Hackathon config YAML")
    parser.add_argument("--github-token", default=None, help="GitHub token override")
    parser.add_argument("--gitlab-token", default=None, help="GitLab token override")
    parser.add_argument(
        "--analyze",
        action="store_true",
        help="Run temporal originality analysis after ingestion",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Run ingest + analysis pipeline and write team markdown reports",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        specs = load_repo_specs(args.input)
        app_config = load_app_config(args.config)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Configuration error: {exc}")
        return 1

    total_commits = 0
    total_errors = 0
    reports = []
    submission_map = _load_submission_map(args.input)

    for spec in specs:
        result = ingest_repo(
            spec,
            github_token=args.github_token,
            gitlab_token=args.gitlab_token,
        )
        total_commits += len(result.commits)
        total_errors += len(result.errors)
        temporal_report = analyze_repo(result, app_config.hackathon_window) if args.report or args.analyze else None

        print(f"{spec.team} | {spec.repo_url} | commits={len(result.commits)}")
        if temporal_report and args.analyze:
            largest_pre = (
                len(temporal_report.largest_pre_commit.files_changed)
                if temporal_report.largest_pre_commit
                else 0
            )
            first_in_window = (
                temporal_report.first_in_window_commit.timestamp
                if temporal_report.first_in_window_commit
                else "none"
            )
            print(
                "  analysis: "
                f"pre={temporal_report.pre_window} "
                f"in={temporal_report.in_window} "
                f"post={temporal_report.post_window} "
                f"pre_pct={temporal_report.pre_window_pct:.1f}% "
                f"largest_pre_files={largest_pre} "
                f"first_in_window={first_in_window} "
                f"risk={temporal_report.risk_flag} ({temporal_report.risk_reason})"
            )

        if args.report:
            genai_report, genai_warning = analyze_genai_optional(result)
            if genai_warning:
                print(f"  warning: {genai_warning}")

            submission = _find_submission_for_spec(
                spec.team,
                spec.repo_url,
                submission_map,
            )
            reports.append(
                build_team_report(
                    spec=spec,
                    ingest_result=result,
                    temporal=temporal_report,
                    genai=genai_report,
                    submission=submission,
                )
            )

        for warning in result.warnings:
            print(f"  warning: {warning}")
        for error in result.errors:
            print(f"  error: {error}")

    if args.report:
        output_dir = Path("civic-hacks-2026") / "reports"
        written = write_reports(output_dir, reports)
        print(f"Wrote {len(written)} report files to {output_dir}")

    print(f"Processed repos: {len(specs)}")
    print(f"Total commits: {total_commits}")
    print(f"Total errors: {total_errors}")
    return 0


def _load_submission_map(input_path: str) -> list:
    try:
        return load_submissions(input_path)
    except (FileNotFoundError, ValueError):
        return []


def _normalize_repo_url(url: str) -> str:
    normalized = (url or "").strip().lower()
    return normalized.removesuffix(".git")


def _find_submission_for_spec(team: str, repo_url: str, submissions: list):
    normalized_repo = _normalize_repo_url(repo_url)
    for submission in submissions:
        for candidate in submission.repo_urls:
            if _normalize_repo_url(candidate) == normalized_repo:
                return submission

    lowered_team = team.strip().lower()
    for submission in submissions:
        if submission.title.strip().lower() == lowered_team:
            return submission
    return None


if __name__ == "__main__":
    raise SystemExit(main())
