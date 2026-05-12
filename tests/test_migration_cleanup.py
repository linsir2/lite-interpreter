"""Guardrails that keep legacy product-surface residue from returning."""

from __future__ import annotations

import re
import subprocess
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_AUDIT_SPEC = spec_from_file_location("audit_local_residue", PROJECT_ROOT / "scripts" / "audit_local_residue.py")
assert _AUDIT_SPEC and _AUDIT_SPEC.loader
_AUDIT_MODULE = module_from_spec(_AUDIT_SPEC)
sys.modules[_AUDIT_SPEC.name] = _AUDIT_MODULE
_AUDIT_SPEC.loader.exec_module(_AUDIT_MODULE)

REVIEW_FIRST = _AUDIT_MODULE.REVIEW_FIRST
SAFE_HISTORICAL = _AUDIT_MODULE.SAFE_HISTORICAL
delete_safe_residue = _AUDIT_MODULE.delete_safe_residue
detect_local_residue = _AUDIT_MODULE.detect_local_residue


def _tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "-c", "core.quotepath=off", "ls-files"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def _read_text(relative_path: str) -> str:
    try:
        return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _tracked_text_matches(pattern: re.Pattern[str], *, allowed_paths: set[str]) -> dict[str, str]:
    matches: dict[str, str] = {}
    for relative_path in _tracked_files():
        if relative_path in allowed_paths:
            continue
        try:
            content = _read_text(relative_path)
        except UnicodeDecodeError:
            continue
        matched = pattern.search(content)
        if matched:
            matches[relative_path] = matched.group(0)
    return matches


def test_legacy_frontend_mentions_are_limited_to_explanation_and_reference_docs():
    legacy_frontend_token = "".join(["stream", "lit"])
    pattern = re.compile(legacy_frontend_token, re.IGNORECASE)
    allowed_paths = {
        ".gitignore",
        "docs/explanation/architecture.md",
        "docs/reference/project-status.md",
        "docs/PRD.md",
        "docs/架构设计文档.md",
        "scripts/audit_local_residue.py",
    }
    matches = _tracked_text_matches(pattern, allowed_paths=allowed_paths)
    assert not matches, f"Unexpected legacy frontend mentions escaped the allowlist: {matches}"


def test_legacy_product_routes_only_appear_in_route_surface_test():
    pattern = re.compile(
        "|".join(
            [
                re.escape("/api/" + "session/login"),
                re.escape("/api/" + "session/me"),
                re.escape("/api/" + "tasks"),
                re.escape("/api/" + "executions"),
                re.escape("/api/" + "uploads"),
                re.escape("/api/" + "knowledge/assets"),
                re.escape("/api/" + "skills"),
                re.escape("/api/" + "audit/logs"),
            ]
        )
    )
    matches = _tracked_text_matches(pattern, allowed_paths={"tests/test_api_route_surface.py"})
    assert not matches, f"Legacy product routes appeared outside the route-surface guardrail: {matches}"


def test_legacy_frontend_port_is_absent_from_tracked_files():
    old_frontend_port = "".join(["85", "01"])
    pattern = re.compile(rf"(?<!\d){old_frontend_port}(?!\d)")
    matches = _tracked_text_matches(pattern, allowed_paths=set())
    assert not matches, f"Legacy frontend port leaked back into tracked files: {matches}"


def test_local_legacy_frontend_directory_is_not_tracked():
    tracked = set(_tracked_files())
    legacy_frontend_path = "." + "".join(["stream", "lit"]) + "/"
    assert all(not path.startswith(legacy_frontend_path) for path in tracked)


def test_local_residue_audit_classifies_safe_and_review_first_entries(tmp_path: Path):
    legacy_frontend_dir = "." + "".join(["stream", "lit"])
    (tmp_path / legacy_frontend_dir).mkdir()
    (tmp_path / ".omx").mkdir()
    (tmp_path / "config.yaml").write_text("sidecar: true\n", encoding="utf-8")

    records = detect_local_residue(tmp_path)
    categories = {record.relative_path: record.category for record in records}

    assert categories[legacy_frontend_dir] == SAFE_HISTORICAL
    assert categories[".omx"] == REVIEW_FIRST
    assert categories["config.yaml"] == REVIEW_FIRST


def test_local_residue_delete_only_removes_allowlisted_safe_entries(tmp_path: Path):
    legacy_frontend_dir = "." + "".join(["stream", "lit"])
    (tmp_path / legacy_frontend_dir).mkdir()
    (tmp_path / "logs").mkdir()

    records = detect_local_residue(tmp_path)
    deleted = delete_safe_residue(records)

    assert deleted == [legacy_frontend_dir]
    assert not (tmp_path / legacy_frontend_dir).exists()
    assert (tmp_path / "logs").exists()
