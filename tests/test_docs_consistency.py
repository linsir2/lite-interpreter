"""Repository documentation consistency checks."""

from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_project_status_is_the_only_hardcoded_test_baseline_source():
    baseline_pattern = re.compile(r"\b\d+\s+passed(?:,\s+\d+\s+skipped)?\b")
    allowed_paths = {"docs/project_status.md"}
    checked_paths = [
        "README.md",
        "docs/project_status.md",
        "docs/development_guide.md",
        "docs/testing.md",
    ]

    for relative_path in checked_paths:
        matches = baseline_pattern.findall(_read(relative_path))
        if relative_path in allowed_paths:
            assert matches, f"{relative_path} should record the current verified baseline"
        else:
            assert not matches, (
                f"{relative_path} should reference docs/project_status.md instead of hardcoding test counts"
            )


def test_primary_docs_reference_project_status_truth_source():
    primary_docs = [
        "README.md",
        "docs/architecture.md",
        "docs/development_guide.md",
        "docs/deployment.md",
        "docs/testing.md",
        "项目二.md",
    ]

    for relative_path in primary_docs:
        assert "docs/project_status.md" in _read(relative_path), (
            f"{relative_path} should reference docs/project_status.md"
        )
