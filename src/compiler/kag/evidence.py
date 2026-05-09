"""Compile static and dynamic evidence into canonical material patches."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from config.settings import OUTPUT_DIR
from pydantic import Field

from src.blackboard.schema import BusinessDocumentState, StructuredDatasetState
from src.common.contracts import StaticEvidenceRecord

from .types import (
    BusinessContextDelta,
    CompilerStateModel,
    EvidenceCompilationInput,
)

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(?P<payload>.*?)```", re.IGNORECASE | re.DOTALL)
_CONTEXT_PREFIXES = {
    "rule": "rules",
    "rules": "rules",
    "规则": "rules",
    "metric": "metrics",
    "metrics": "metrics",
    "指标": "metrics",
    "filter": "filters",
    "filters": "filters",
    "筛选": "filters",
    "过滤": "filters",
}


class EvidenceMaterialPatch(CompilerStateModel):
    """Compiler delta that carries canonical material models, not shadow schemas."""

    structured_datasets: list[StructuredDatasetState] = Field(default_factory=list)
    business_documents: list[BusinessDocumentState] = Field(default_factory=list)
    business_context_delta: BusinessContextDelta = Field(default_factory=BusinessContextDelta)
    knowledge_hits: list[dict[str, Any]] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    material_refresh_actions: list[str] = Field(default_factory=list)
    diagnostics: dict[str, Any] = Field(default_factory=dict)


def _unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def _truncate(text: str, limit: int) -> str:
    normalized = str(text or "").strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(limit - 3, 0)] + "..."


def _safe_name(value: str, default: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "_", str(value or "").strip()).strip("._-")
    return cleaned or default


def _stable_sha256(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _normalize_number(value: Any) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    text = str(value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return int(number) if number.is_integer() else number


def _parse_json_payloads(text: str) -> list[Any]:
    payloads: list[Any] = []
    normalized = str(text or "").strip()
    if not normalized:
        return payloads
    candidates = [normalized]
    for match in _JSON_FENCE_RE.finditer(normalized):
        payload = str(match.group("payload") or "").strip()
        if payload:
            candidates.append(payload)
    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            payloads.append(json.loads(candidate))
        except json.JSONDecodeError:
            continue
    return payloads


def _iter_candidate_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, Mapping)]
    if isinstance(payload, Mapping):
        items = payload.get("items")
        if isinstance(items, list):
            return [dict(item) for item in items if isinstance(item, Mapping)]
        return [dict(payload)]
    return []


def _extract_context_from_text(text: str) -> dict[str, list[str]]:
    extracted = {"rules": [], "metrics": [], "filters": []}
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = re.match(r"^\s*([A-Za-z\u4e00-\u9fff]+)\s*[:：-]\s*(.+?)\s*$", line)
        if not match:
            continue
        prefix_raw = match.group(1).strip()
        prefix = prefix_raw.lower()
        slot = _CONTEXT_PREFIXES.get(prefix) or _CONTEXT_PREFIXES.get(prefix_raw)
        if slot is None:
            continue
        extracted[slot].append(match.group(2).strip())
    return extracted


def _append_context(delta: BusinessContextDelta, values: Mapping[str, list[str]], source_ref: str) -> None:
    for field_name in ("rules", "metrics", "filters"):
        merged = list(getattr(delta, field_name))
        merged.extend(str(item).strip() for item in values.get(field_name, []) if str(item).strip())
        setattr(delta, field_name, _unique_strings(merged))
    if any(values.get(field_name) for field_name in ("rules", "metrics", "filters")):
        delta.sources = _unique_strings([*delta.sources, source_ref])


def _build_source_meta(
    *,
    source_kind: str,
    title: str,
    text: str,
    source_type: str,
    url: str = "",
    explicit_ref: str = "",
) -> dict[str, str]:
    base_ref = explicit_ref or url or f"{source_kind}:{_stable_sha256({'title': title, 'text': text, 'url': url})[:16]}"
    source_sha256 = _stable_sha256({"title": title, "text": text, "url": url, "source_type": source_type})
    return {
        "ref": base_ref,
        "title": title,
        "text": text,
        "url": url,
        "source_type": source_type,
        "source_sha256": source_sha256,
    }


def _build_dataset_row(candidate: Mapping[str, Any], source_meta: Mapping[str, str]) -> dict[str, Any] | None:
    entity = str(candidate.get("entity") or "").strip()
    metric = str(candidate.get("metric") or "").strip()
    period = str(candidate.get("period") or "").strip()
    value = _normalize_number(candidate.get("value"))
    if not (entity and metric and period) or value is None:
        return None

    unit = str(candidate.get("unit") or "").strip()
    currency = str(candidate.get("currency") or "").strip()
    if not unit and not currency:
        return None

    source = str(candidate.get("source") or candidate.get("source_url") or source_meta.get("ref") or "").strip()
    if not source:
        return None

    source_quote = str(candidate.get("source_quote") or source_meta.get("text") or "").strip()
    return {
        "entity": entity,
        "metric": metric,
        "period": period,
        "value": value,
        "unit": unit,
        "currency": currency,
        "source": source,
        "source_url": str(candidate.get("source_url") or source_meta.get("url") or "").strip(),
        "source_type": str(candidate.get("source_type") or source_meta.get("source_type") or "").strip(),
        "source_quote": _truncate(source_quote, 280),
        "source_sha256": str(candidate.get("source_sha256") or source_meta.get("source_sha256") or "").strip(),
    }


def _record_text(record: StaticEvidenceRecord, limit: int) -> str:
    return _truncate(str(record.text or record.snippet or "").strip(), limit)


def _write_dataset_file(
    *,
    rows: list[dict[str, Any]],
    compilation_input: EvidenceCompilationInput,
) -> StructuredDatasetState:
    output_root = Path(OUTPUT_DIR).resolve() / compilation_input.tenant_id / compilation_input.workspace_id
    output_root = output_root / f"evidence-materials-{compilation_input.task_id}"
    output_root.mkdir(parents=True, exist_ok=True)

    payload = {
        "items": rows,
        "metadata": {
            "source": compilation_input.source,
            "query": compilation_input.query,
            "row_count": len(rows),
        },
    }
    payload_bytes = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    file_sha256 = hashlib.sha256(payload_bytes).hexdigest()
    file_name = f"{_safe_name(compilation_input.source, 'evidence')}_{file_sha256[:12]}.json"
    file_path = output_root / file_name
    file_path.write_bytes(payload_bytes)
    return StructuredDatasetState(
        file_name=file_name,
        path=str(file_path),
        file_sha256=file_sha256,
        dataset_schema="",
        load_kwargs={"format": "json"},
    )


def compile_external_evidence(compilation_input: EvidenceCompilationInput) -> EvidenceMaterialPatch:
    diagnostics: dict[str, Any] = {
        "source": compilation_input.source,
        "record_count": len(compilation_input.records),
        "finding_count": len(compilation_input.findings),
        "artifact_ref_count": len(compilation_input.artifact_refs),
        "accepted_dataset_rows": 0,
        "skipped_structured_candidates": 0,
        "generated_files": [],
    }

    evidence_refs = _unique_strings(list(compilation_input.artifact_refs))
    knowledge_hits: list[dict[str, Any]] = []
    business_context_delta = BusinessContextDelta()
    accepted_rows: list[dict[str, Any]] = []
    seen_rows: set[str] = set()

    def handle_source(
        *,
        source_meta: dict[str, str],
        candidate_payloads: list[Any],
        context_seed: Mapping[str, Any] | None = None,
    ) -> None:
        nonlocal evidence_refs, knowledge_hits, accepted_rows, seen_rows

        source_ref = str(source_meta.get("ref") or "").strip()
        if source_ref:
            evidence_refs = _unique_strings([*evidence_refs, source_ref])

        context_payload = {"rules": [], "metrics": [], "filters": []}
        if isinstance(context_seed, Mapping):
            for field_name in ("rules", "metrics", "filters"):
                context_payload[field_name] = [
                    str(item).strip() for item in list(context_seed.get(field_name) or []) if str(item).strip()
                ]
        parsed_context = _extract_context_from_text(source_meta.get("text", ""))
        for field_name in ("rules", "metrics", "filters"):
            context_payload[field_name].extend(parsed_context.get(field_name, []))
            context_payload[field_name] = _unique_strings(context_payload[field_name])
        _append_context(business_context_delta, context_payload, source_ref)

        accepted_here = False
        for payload in candidate_payloads:
            for candidate in _iter_candidate_rows(payload):
                row = _build_dataset_row(candidate, source_meta)
                if row is None:
                    diagnostics["skipped_structured_candidates"] += 1
                    continue
                row_key = json.dumps(row, ensure_ascii=False, sort_keys=True)
                if row_key in seen_rows:
                    continue
                seen_rows.add(row_key)
                accepted_rows.append(row)
                accepted_here = True
                if len(accepted_rows) >= max(1, compilation_input.max_rows):
                    diagnostics["truncated_dataset_rows"] = True
                    break
            if len(accepted_rows) >= max(1, compilation_input.max_rows):
                break

        if accepted_here:
            return

        text = str(source_meta.get("text") or "").strip()
        if not text:
            return
        knowledge_hits.append(
            {
                "text": text,
                "title": str(source_meta.get("title") or "").strip(),
                "source": source_ref,
                "type": str(source_meta.get("source_type") or "").strip(),
                "score": 1.0,
                "metadata": {
                    "source_url": str(source_meta.get("url") or "").strip(),
                    "source_sha256": str(source_meta.get("source_sha256") or "").strip(),
                },
            }
        )

    for index, record in enumerate(compilation_input.records):
        source_text = _record_text(record, compilation_input.max_text_chars)
        source_meta = _build_source_meta(
            source_kind=compilation_input.source,
            title=str(record.title or f"record_{index + 1}").strip(),
            text=source_text,
            source_type=str(record.source_type or "static_evidence"),
            url=str(record.url or "").strip(),
        )
        metadata = dict(record.metadata or {})
        candidate_payloads: list[Any] = []
        for key in ("structured_rows", "structured_data", "dataset_rows"):
            candidate_payloads.append(metadata.get(key))
        candidate_payloads.extend(_parse_json_payloads(source_text))
        handle_source(
            source_meta=source_meta,
            candidate_payloads=candidate_payloads,
            context_seed=metadata.get("business_context") if isinstance(metadata.get("business_context"), Mapping) else None,
        )

    for index, finding in enumerate(compilation_input.findings):
        source_text = _truncate(str(finding or "").strip(), compilation_input.max_text_chars)
        source_meta = _build_source_meta(
            source_kind=compilation_input.source,
            title=f"{compilation_input.source}_finding_{index + 1}",
            text=source_text,
            source_type="dynamic_finding" if compilation_input.source == "dynamic_resume" else "static_evidence",
        )
        handle_source(source_meta=source_meta, candidate_payloads=_parse_json_payloads(source_text))

    structured_datasets: list[StructuredDatasetState] = []
    if accepted_rows:
        dataset_patch = _write_dataset_file(rows=accepted_rows, compilation_input=compilation_input)
        structured_datasets.append(dataset_patch)
        diagnostics["generated_files"].append(dataset_patch.path)
    diagnostics["accepted_dataset_rows"] = len(accepted_rows)

    material_refresh_actions: list[str] = []
    if structured_datasets:
        material_refresh_actions.append("data_inspector")
    elif knowledge_hits:
        material_refresh_actions.append("context_builder")

    return EvidenceMaterialPatch(
        structured_datasets=structured_datasets,
        business_context_delta=business_context_delta,
        knowledge_hits=knowledge_hits,
        evidence_refs=_unique_strings(evidence_refs),
        material_refresh_actions=material_refresh_actions,
        diagnostics=diagnostics,
    )
