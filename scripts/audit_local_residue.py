#!/usr/bin/env python3
"""Audit and optionally delete known local historical residue."""

from __future__ import annotations

import argparse
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ResidueRule:
    relative_path: str
    category: str
    delete_allowed: bool
    reason: str


@dataclass(frozen=True)
class ResidueRecord:
    relative_path: str
    category: str
    delete_allowed: bool
    reason: str
    kind: str
    absolute_path: Path


SAFE_HISTORICAL = "safe historical residue"
REVIEW_FIRST = "review-first local state"

DEFAULT_RULES = [
    ResidueRule(
        relative_path=".streamlit",
        category=SAFE_HISTORICAL,
        delete_allowed=True,
        reason="Legacy local frontend preferences from the retired product surface.",
    ),
    ResidueRule(
        relative_path=".deer-flow",
        category=REVIEW_FIRST,
        delete_allowed=False,
        reason="Local DeerFlow state; inspect before deleting because it may still be useful.",
    ),
    ResidueRule(
        relative_path=".omx",
        category=REVIEW_FIRST,
        delete_allowed=False,
        reason="Local agent planning/state; inspect before deleting.",
    ),
    ResidueRule(
        relative_path="data",
        category=REVIEW_FIRST,
        delete_allowed=False,
        reason="Runtime uploads, outputs, and persisted state; inspect before deleting.",
    ),
    ResidueRule(
        relative_path="logs",
        category=REVIEW_FIRST,
        delete_allowed=False,
        reason="Runtime logs; inspect before deleting.",
    ),
    ResidueRule(
        relative_path="config.yaml",
        category=REVIEW_FIRST,
        delete_allowed=False,
        reason="Possible local sidecar config residue; inspect before deleting.",
    ),
]


def detect_local_residue(project_root: Path) -> list[ResidueRecord]:
    records: list[ResidueRecord] = []
    for rule in DEFAULT_RULES:
        candidate = project_root / rule.relative_path
        if not candidate.exists():
            continue
        records.append(
            ResidueRecord(
                relative_path=rule.relative_path,
                category=rule.category,
                delete_allowed=rule.delete_allowed,
                reason=rule.reason,
                kind="directory" if candidate.is_dir() else "file",
                absolute_path=candidate,
            )
        )
    return records


def delete_safe_residue(records: list[ResidueRecord]) -> list[str]:
    deleted: list[str] = []
    for record in records:
        if not record.delete_allowed or not record.absolute_path.exists():
            continue
        if record.absolute_path.is_dir():
            shutil.rmtree(record.absolute_path)
        else:
            record.absolute_path.unlink()
        deleted.append(record.relative_path)
    return deleted


def _render_section(title: str, records: list[ResidueRecord]) -> list[str]:
    lines = [f"{title}:"]
    if not records:
        lines.append("  - none")
        return lines
    for record in records:
        lines.append(f"  - {record.relative_path} ({record.kind})")
        lines.append(f"    {record.reason}")
    return lines


def render_report(records: list[ResidueRecord], *, deleted: list[str] | None = None) -> str:
    safe_records = [record for record in records if record.category == SAFE_HISTORICAL]
    review_records = [record for record in records if record.category == REVIEW_FIRST]
    lines = ["Known local residue audit", ""]
    lines.extend(_render_section(SAFE_HISTORICAL, safe_records))
    lines.append("")
    lines.extend(_render_section(REVIEW_FIRST, review_records))
    lines.append("")
    if deleted is None:
        lines.append("Mode: dry-run (nothing deleted)")
    elif deleted:
        lines.append("Deleted:")
        for item in deleted:
            lines.append(f"  - {item}")
    else:
        lines.append("Delete mode ran, but no safe historical residue was present.")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit local historical residue left behind after product-surface migration.")
    parser.add_argument(
        "--project-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="Project root to inspect. Defaults to the repository root.",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Delete only the allowlisted safe historical residue after auditing.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    project_root = Path(args.project_root).resolve()
    records = detect_local_residue(project_root)
    deleted = delete_safe_residue(records) if args.delete else None
    print(render_report(records, deleted=deleted))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
