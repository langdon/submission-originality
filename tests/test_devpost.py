from __future__ import annotations

from pathlib import Path

import pytest

from src.devpost import load_submissions


def test_load_submissions_from_csv_extracts_required_fields() -> None:
    submissions = load_submissions(Path("tests/fixtures/devpost_submissions.csv"))

    assert len(submissions) == 2

    first = submissions[0]
    assert first.title == "RoadSafe AI"
    assert first.description == "AI co-pilot for safer street design"
    assert first.track == "Mobility"
    assert first.team_members == ["Alex Kim", "Pat Lee"]
    assert first.repo_urls == ["https://github.com/example/roadsafe-ai"]
    assert first.submitted_at == "2026-02-20T10:30:00-05:00"

    second = submissions[1]
    assert second.repo_urls == ["https://gitlab.com/civic/openbudget-lens"]


def test_load_submissions_handles_missing_fields_gracefully() -> None:
    submissions = load_submissions(Path("tests/fixtures/devpost_sparse.csv"))

    assert len(submissions) == 1
    item = submissions[0]
    assert item.title == "Unnamed"
    assert item.description == ""
    assert item.track == ""
    assert item.team_members == []
    assert item.repo_urls == []
    assert item.submitted_at is None


def test_load_submissions_from_devpost_url(monkeypatch: pytest.MonkeyPatch) -> None:
    fixture_html = Path("tests/fixtures/devpost_project.html").read_text(encoding="utf-8")

    class Response:
        status_code = 200
        text = fixture_html

        def raise_for_status(self) -> None:
            return

    def fake_get(url: str, timeout: int = 30) -> Response:
        assert url == "https://devpost.com/software/transit-hero"
        assert timeout == 30
        return Response()

    monkeypatch.setattr("src.devpost.requests.get", fake_get)

    submissions = load_submissions("https://devpost.com/software/transit-hero")
    assert len(submissions) == 1

    item = submissions[0]
    assert item.title == "Transit Hero"
    assert item.description == "Realtime transit assistant for riders."
    assert item.track == "City Hacks 2026 - Mobility"
    assert item.team_members == ["Alex Kim", "Pat Lee"]
    assert item.repo_urls == ["https://github.com/acme/transit-hero"]
    assert item.submitted_at == "2026-02-20T12:34:56-05:00"
