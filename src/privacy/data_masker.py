"""Recursive payload masking helpers used before data leaves the control plane."""
from __future__ import annotations

from collections import Counter
from typing import Any

from src.privacy.desensitization_rules import get_redaction_rules


def _empty_report() -> dict[str, Any]:
    return {
        "match_count": 0,
        "rule_hits": {},
        "findings": [],
    }


def merge_redaction_reports(*reports: dict[str, Any]) -> dict[str, Any]:
    """Merge multiple redaction reports into one summary."""
    counter: Counter[str] = Counter()
    findings: list[dict[str, Any]] = []
    match_count = 0
    for report in reports:
        if not isinstance(report, dict):
            continue
        match_count += int(report.get("match_count", 0) or 0)
        counter.update({str(key): int(value or 0) for key, value in (report.get("rule_hits") or {}).items()})
        findings.extend(list(report.get("findings") or []))
    return {
        "match_count": match_count,
        "rule_hits": dict(counter),
        "findings": findings,
    }


def mask_text(text: str, rule_names: list[str] | None = None) -> tuple[str, dict[str, Any]]:
    """Mask sensitive values in text according to the configured rules."""
    if not text:
        return text, _empty_report()

    redacted = text
    findings: list[dict[str, Any]] = []
    counter: Counter[str] = Counter()
    for rule in get_redaction_rules(rule_names):
        matches = list(rule.pattern.finditer(redacted))
        if not matches:
            continue
        redacted = rule.pattern.sub(rule.replacement, redacted)
        counter[rule.name] += len(matches)
        findings.extend(
            {
                "rule": rule.name,
                "description": rule.description,
                "match": match.group(0),
            }
            for match in matches
        )
    return redacted, {
        "match_count": sum(counter.values()),
        "rule_hits": dict(counter),
        "findings": findings,
    }


def mask_payload(payload: Any, rule_names: list[str] | None = None) -> tuple[Any, dict[str, Any]]:
    """Recursively redact strings inside dict/list payloads."""
    if isinstance(payload, str):
        return mask_text(payload, rule_names)
    if isinstance(payload, dict):
        redacted: dict[str, Any] = {}
        report = _empty_report()
        for key, value in payload.items():
            masked_value, child_report = mask_payload(value, rule_names)
            redacted[key] = masked_value
            report = merge_redaction_reports(report, child_report)
        return redacted, report
    if isinstance(payload, list):
        redacted_items: list[Any] = []
        report = _empty_report()
        for item in payload:
            masked_item, child_report = mask_payload(item, rule_names)
            redacted_items.append(masked_item)
            report = merge_redaction_reports(report, child_report)
        return redacted_items, report
    if isinstance(payload, tuple):
        redacted_items: list[Any] = []
        report = _empty_report()
        for item in payload:
            masked_item, child_report = mask_payload(item, rule_names)
            redacted_items.append(masked_item)
            report = merge_redaction_reports(report, child_report)
        return tuple(redacted_items), report
    return payload, _empty_report()
