from __future__ import annotations

import argparse

from src.config import load_app_config, load_repo_specs
from src.ingest import ingest_repo


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest submission repos across hosts")
    parser.add_argument("--input", required=True, help="CSV or YAML submissions file")
    parser.add_argument("--config", required=True, help="Hackathon config YAML")
    parser.add_argument("--github-token", default=None, help="GitHub token override")
    parser.add_argument("--gitlab-token", default=None, help="GitLab token override")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        specs = load_repo_specs(args.input)
        _ = load_app_config(args.config)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Configuration error: {exc}")
        return 1

    total_commits = 0
    total_errors = 0

    for spec in specs:
        result = ingest_repo(
            spec,
            github_token=args.github_token,
            gitlab_token=args.gitlab_token,
        )
        total_commits += len(result.commits)
        total_errors += len(result.errors)

        print(f"{spec.team} | {spec.repo_url} | commits={len(result.commits)}")
        for warning in result.warnings:
            print(f"  warning: {warning}")
        for error in result.errors:
            print(f"  error: {error}")

    print(f"Processed repos: {len(specs)}")
    print(f"Total commits: {total_commits}")
    print(f"Total errors: {total_errors}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
