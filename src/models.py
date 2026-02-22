from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RepoSpec:
    team: str
    repo_url: str


@dataclass(frozen=True)
class Commit:
    sha: str
    author: str
    email: str
    timestamp: str
    message: str
    files_changed: list[str]


@dataclass
class IngestResult:
    spec: RepoSpec
    commits: list[Commit] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors
