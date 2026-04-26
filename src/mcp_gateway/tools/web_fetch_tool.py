"""Governed HTTP GET tools for static evidence collection."""

from __future__ import annotations

import json
import re
from html import unescape
from typing import Any
from urllib.parse import urlparse

import httpx
from config.settings import (
    STATIC_EVIDENCE_ALLOWED_DOMAINS,
    STATIC_EVIDENCE_MAX_BYTES,
    STATIC_EVIDENCE_MAX_REDIRECTS,
    STATIC_EVIDENCE_MAX_SEARCH_RESULTS,
    STATIC_EVIDENCE_TIMEOUT_SECONDS,
    TAVILY_API_KEY,
)

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def _strip_html(value: str, limit: int = 2000) -> str:
    text = unescape(_TAG_RE.sub(" ", str(value or "")))
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text[:limit]


def _normalize_domain(url: str) -> str:
    return urlparse(url).hostname or ""


def _domain_allowed(domain: str, allowlist: list[str]) -> bool:
    normalized = str(domain or "").strip().lower()
    if not normalized:
        return False
    for candidate in allowlist:
        item = str(candidate or "").strip().lower()
        if not item:
            continue
        if normalized == item or normalized.endswith(f".{item}"):
            return True
    return False


def _validate_url(url: str, allowlist: list[str]) -> str:
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http/https URLs are allowed.")
    domain = _normalize_domain(url)
    if not _domain_allowed(domain, allowlist):
        raise ValueError(f"Domain `{domain}` is not on the static evidence allowlist.")
    return domain


class WebFetchTool:
    CAPABILITY_ID = "web_fetch"

    @staticmethod
    def run(
        *,
        url: str,
        allowlist: list[str] | None = None,
        timeout_seconds: int | None = None,
        max_bytes: int | None = None,
        max_redirects: int | None = None,
    ) -> dict[str, Any]:
        effective_allowlist = list(allowlist or STATIC_EVIDENCE_ALLOWED_DOMAINS)
        domain = _validate_url(url, effective_allowlist)
        timeout = float(timeout_seconds or STATIC_EVIDENCE_TIMEOUT_SECONDS)
        byte_limit = int(max_bytes or STATIC_EVIDENCE_MAX_BYTES)
        redirect_limit = int(max_redirects or STATIC_EVIDENCE_MAX_REDIRECTS)
        transport = httpx.HTTPTransport(retries=0)

        with httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            max_redirects=redirect_limit,
            transport=transport,
            headers={"User-Agent": "lite-interpreter-static-evidence/1.0"},
        ) as client:
            response = client.get(url)
            response.raise_for_status()
            content = response.content[:byte_limit]
            content_type = str(response.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
            text = content.decode("utf-8", errors="ignore")
            payload: dict[str, Any] = {
                "url": str(response.url),
                "domain": domain,
                "status_code": response.status_code,
                "content_type": content_type,
                "text": _strip_html(text, limit=6000),
            }
            if content_type.endswith("/json") or content_type == "application/json":
                try:
                    payload["json"] = json.loads(text)
                except Exception:
                    payload["json"] = None
            return payload


class WebSearchTool:
    CAPABILITY_ID = "web_search"

    @staticmethod
    def run(
        *,
        query: str,
        allowlist: list[str] | None = None,
        limit: int | None = None,
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        api_key = TAVILY_API_KEY
        if not api_key:
            return {
                "query": str(query or "").strip(),
                "provider": "tavily",
                "items": [],
                "error": "TAVILY_API_KEY is not configured.",
            }
        max_results = max(1, min(int(limit or STATIC_EVIDENCE_MAX_SEARCH_RESULTS), STATIC_EVIDENCE_MAX_SEARCH_RESULTS))
        timeout = float(timeout_seconds or STATIC_EVIDENCE_TIMEOUT_SECONDS)

        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": api_key,
                    "query": str(query or "").strip(),
                    "search_depth": "basic",
                    "max_results": max_results,
                    "include_answer": False,
                    "include_raw_content": False,
                },
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            data = response.json()

        items: list[dict[str, Any]] = []
        for result in list(data.get("results") or [])[:max_results]:
            url = str(result.get("url") or "")
            items.append(
                {
                    "title": str(result.get("title") or ""),
                    "url": url,
                    "snippet": str(result.get("content") or "")[:400],
                    "domain": urlparse(url).hostname or "",
                }
            )
        return {
            "query": str(query or "").strip(),
            "provider": "tavily",
            "items": items,
        }
