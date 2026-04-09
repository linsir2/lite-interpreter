"""Helpers for scanning potentially sensitive text and payloads."""

from __future__ import annotations

from typing import Any

from src.privacy.desensitization_rules import get_redaction_rules


def scan_text(text: str, rule_names: list[str] | None = None) -> list[dict[str, Any]]:
    """Return match metadata for sensitive patterns found in text."""
    findings: list[dict[str, Any]] = []
    if not text:
        return findings

    for rule in get_redaction_rules(rule_names):
        for match in rule.pattern.finditer(text):
            findings.append(
                {
                    "rule": rule.name,
                    "description": rule.description,
                    "match": match.group(0),
                    "start": match.start(),
                    "end": match.end(),
                }
            )
    return findings


def scan_payload(payload: Any, rule_names: list[str] | None = None) -> list[dict[str, Any]]:
    """Recursively scan strings embedded in dict/list payloads."""
    findings: list[dict[str, Any]] = []

    def _walk(value: Any, path: str) -> None:
        if isinstance(value, str):
            for finding in scan_text(value, rule_names):
                findings.append({**finding, "path": path})
            return
        if isinstance(value, dict):
            for key, nested in value.items():
                next_path = f"{path}.{key}" if path else str(key)
                _walk(nested, next_path)
            return
        if isinstance(value, (list, tuple, set)):
            for index, nested in enumerate(value):
                next_path = f"{path}[{index}]"
                _walk(nested, next_path)

    _walk(payload, "")
    return findings
