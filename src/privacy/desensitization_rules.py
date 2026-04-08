"""Built-in desensitization rules used by lite-interpreter."""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass

Replacement = str | Callable[[re.Match[str]], str]


@dataclass(frozen=True)
class RedactionRule:
    """One text redaction rule."""

    name: str
    pattern: re.Pattern[str]
    replacement: Replacement
    description: str


def _preserve_prefix(match: re.Match[str], prefix_groups: int = 1) -> str:
    prefix = "".join(match.group(index) or "" for index in range(1, prefix_groups + 1))
    return f"{prefix}[REDACTED]"


DEFAULT_REDACTION_RULES: tuple[RedactionRule, ...] = (
    RedactionRule(
        name="authorization",
        pattern=re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)([A-Za-z0-9\-._~+/]+=*)"),
        replacement=lambda match: _preserve_prefix(match),
        description="Authorization bearer token",
    ),
    RedactionRule(
        name="authorization",
        pattern=re.compile(r"(?i)\bBearer\s+([A-Za-z0-9\-._~+/]+=*)"),
        replacement="Bearer [REDACTED]",
        description="Bare bearer token",
    ),
    RedactionRule(
        name="api_key",
        pattern=re.compile(r"(?i)(api[_-]?key\s*[:=]\s*[\"']?)([^\"'\s,;]+)"),
        replacement=lambda match: _preserve_prefix(match),
        description="API key style credential",
    ),
    RedactionRule(
        name="access_token",
        pattern=re.compile(r"(?i)(access[_-]?token\s*[:=]\s*[\"']?)([^\"'\s,;]+)"),
        replacement=lambda match: _preserve_prefix(match),
        description="Access token style credential",
    ),
    RedactionRule(
        name="uri_credentials",
        pattern=re.compile(r"([a-zA-Z][a-zA-Z0-9+.\-]*://)([^:/@\s]+):([^@/\s]+)@"),
        replacement=lambda match: f"{match.group(1)}[REDACTED]:[REDACTED]@",
        description="Credentials embedded in URIs",
    ),
    RedactionRule(
        name="email",
        pattern=re.compile(r"(?<![\w.-])([A-Za-z0-9._%+-]+)@([A-Za-z0-9.-]+\.[A-Za-z]{2,})(?![\w.-])"),
        replacement="[REDACTED_EMAIL]",
        description="Email address",
    ),
    RedactionRule(
        name="phone",
        pattern=re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)"),
        replacement="[REDACTED_PHONE]",
        description="Mobile phone number",
    ),
    RedactionRule(
        name="id_card",
        pattern=re.compile(r"(?<![\w])(\d{17}[\dXx])(?![\w])"),
        replacement="[REDACTED_ID]",
        description="Chinese ID card number",
    ),
)

DEFAULT_RULE_NAMES: tuple[str, ...] = tuple(rule.name for rule in DEFAULT_REDACTION_RULES)


def get_redaction_rules(rule_names: Iterable[str] | None = None) -> list[RedactionRule]:
    """Resolve configured redaction rules by name."""
    if rule_names is None:
        return list(DEFAULT_REDACTION_RULES)

    wanted = {str(name).strip().lower() for name in rule_names if str(name).strip()}
    if not wanted:
        return list(DEFAULT_REDACTION_RULES)
    return [rule for rule in DEFAULT_REDACTION_RULES if rule.name in wanted]
