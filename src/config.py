from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from src.models import RepoSpec


@dataclass(frozen=True)
class HackathonWindow:
    start_datetime: str
    end_datetime: str
    timezone: str


@dataclass(frozen=True)
class AppConfig:
    hackathon_window: HackathonWindow


def load_repo_specs(input_path: str | Path) -> list[RepoSpec]:
    path = Path(input_path)
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")

    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            return _rows_to_specs(reader, str(path))

    if suffix in {".yaml", ".yml"}:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or []
        rows = _extract_yaml_rows(data)
        return _rows_to_specs(rows, str(path))

    raise ValueError(f"Unsupported input format for {path}. Expected .csv or .yaml/.yml")


def load_app_config(config_path: str | Path) -> AppConfig:
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    window_data = data.get("hackathon_window")
    if not isinstance(window_data, dict):
        raise ValueError("Config must include a 'hackathon_window' mapping")

    required = ["start_datetime", "end_datetime", "timezone"]
    missing = [key for key in required if not window_data.get(key)]
    if missing:
        raise ValueError(
            f"hackathon_window is missing required key(s): {', '.join(missing)}"
        )

    window = HackathonWindow(
        start_datetime=str(window_data["start_datetime"]),
        end_datetime=str(window_data["end_datetime"]),
        timezone=str(window_data["timezone"]),
    )
    return AppConfig(hackathon_window=window)


def _extract_yaml_rows(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]

    if isinstance(data, dict):
        submissions = data.get("submissions")
        if isinstance(submissions, list):
            return [row for row in submissions if isinstance(row, dict)]

    raise ValueError(
        "YAML input must be either a list of items or a mapping with 'submissions'"
    )


def _rows_to_specs(rows: Any, source: str) -> list[RepoSpec]:
    specs: list[RepoSpec] = []
    for idx, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"Invalid row type at {source}:{idx}; expected mapping")

        team = (row.get("team") or "").strip()
        repo_url = (row.get("repo_url") or "").strip()
        if not team or not repo_url:
            raise ValueError(
                f"Invalid row at {source}:{idx}; expected non-empty 'team' and 'repo_url'"
            )

        specs.append(RepoSpec(team=team, repo_url=repo_url))

    return specs
