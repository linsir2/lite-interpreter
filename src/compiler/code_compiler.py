"""Code compiler — build LLM code-generation prompts from ExecutionStrategy constraints.

Consumes the analyst's frozen ExecutionStrategy and reference skills to
produce a constraint-rich prompt.  The LLM call is the coder_node's
responsibility — this module is a pure prompt formatter.
"""

from __future__ import annotations

from typing import Any

from src.common.contracts import ExecutionStrategy


def _summarize_payload(payload: dict[str, Any]) -> str:
    """Build a compact data-availability summary for the codegen prompt."""
    parts: list[str] = []

    input_mounts = payload.get("input_mounts") or []
    structured = [m for m in input_mounts if m.get("kind") == "structured_dataset"]
    documents = [m for m in input_mounts if m.get("kind") == "business_document"]
    evidence = payload.get("static_evidence_bundle") or {}

    if structured:
        names = [m.get("file_name", "?") for m in structured[:10]]
        parts.append(f"- 结构化数据集({len(structured)}): {', '.join(names)}")
    if documents:
        names = [m.get("file_name", "?") for m in documents[:10]]
        parts.append(f"- 业务文档({len(documents)}): {', '.join(names)}")
    if evidence:
        records = evidence.get("records") or []
        if records:
            parts.append(f"- 外部证据记录({len(records)})")

    # External structured knowledge from dynamic exploration (ADR-005 Phase 2)
    external_knowledge = payload.get("external_knowledge") or []
    if external_knowledge:
        lookup_tables = [ek for ek in external_knowledge if ek.get("kind") == "lookup_table"]
        numeric_facts = [ek for ek in external_knowledge if ek.get("kind") == "numeric_fact"]
        textual_findings = [ek for ek in external_knowledge if ek.get("kind") == "textual_finding"]
        if lookup_tables:
            names = [t.get("table_name", "?") for t in lookup_tables]
            parts.append(f"- 结构化查询表({len(lookup_tables)}): {', '.join(names)}")
        if numeric_facts:
            facts = [f"{f.get('entity', '?')}.{f.get('metric', '?')}={f.get('value', '?')}" for f in numeric_facts]
            parts.append(f"- 数值事实({len(numeric_facts)}): {', '.join(facts[:10])}")
        if textual_findings:
            topics = [t.get("topic", "?") for t in textual_findings]
            parts.append(f"- 文本研究发现({len(textual_findings)}): {', '.join(topics[:5])}")

    compiled_knowledge = payload.get("compiled_knowledge") or {}
    rule_specs = compiled_knowledge.get("rule_specs") or []
    metric_specs = compiled_knowledge.get("metric_specs") or []
    filter_specs = compiled_knowledge.get("filter_specs") or []

    if rule_specs:
        parts.append(f"- 编译态业务规则({len(rule_specs)})")
    if metric_specs:
        parts.append(f"- 编译态业务指标({len(metric_specs)})")
    if filter_specs:
        parts.append(f"- 编译态过滤条件({len(filter_specs)})")

    if not parts:
        parts.append("- 无可用数据或知识编译产物")
    return "\n".join(parts)


def _format_skill_reference(skills: list[dict[str, Any]]) -> str:
    """Format pre-defined skills as optional reference patterns."""
    if not skills:
        return "暂无参考技能。"
    lines = []
    for skill in skills[:3]:
        name = skill.get("name", "unknown")
        focus = ", ".join(skill.get("focus_areas", [])[:3]) or "通用分析模式"
        lines.append(f"- {name}: {focus}")
    return "\n".join(lines)


def build_codegen_prompt(
    execution_strategy: ExecutionStrategy,
    skills: list[dict[str, Any]],
    payload: dict[str, Any],
) -> str:
    """Build a constraint-rich prompt for LLM-driven static code generation.

    Args:
        execution_strategy: Frozen analyst plan — the constraint authority.
        skills: Pre-defined codegen skills as optional style reference.
        payload: Runtime payload (input_mounts, compiled_knowledge, etc.).

    Returns:
        A system prompt string for the code-generation LLM call.
    """
    artifact_plan = execution_strategy.artifact_plan
    verification_plan = execution_strategy.verification_plan

    required_artifact_names = [
        spec.file_name for spec in artifact_plan.required_artifacts
    ]
    optional_artifact_names = [
        spec.file_name for spec in artifact_plan.optional_artifacts
    ]
    prohibited = verification_plan.prohibited_extensions or []

    return f"""You are generating Python code for a sandboxed data-analysis task.

## Task Summary
{execution_strategy.summary or '对给定数据执行分析并产出结构化结果。'}

## Hard Constraints (MUST satisfy)

### Network & Iteration Mode
- network_mode: {execution_strategy.network_mode.value}
- iteration_mode: {execution_strategy.iteration_mode.value}
- analysis_mode: {execution_strategy.analysis_mode}
- strategy_family: {execution_strategy.strategy_family}

### Required Artifacts
{chr(10).join(f'- {name}' for name in required_artifact_names) or '- 无强制要求（按需产出）'}

### Optional Artifacts
{chr(10).join(f'- {name}' for name in optional_artifact_names) or '- 无'}

### Prohibited
- 禁止产出的文件后缀: {', '.join(prohibited) if prohibited else '无'}
- 输出根目录: {artifact_plan.output_root}
- Sandbox policy: no network access, no disallowed modules

### Evidence Plan
- research_mode: {execution_strategy.evidence_plan.research_mode}
- allowed_capabilities: {', '.join(execution_strategy.evidence_plan.allowed_capabilities) if execution_strategy.evidence_plan.allowed_capabilities else 'none'}
- search_queries: {', '.join(execution_strategy.evidence_plan.search_queries[:5]) if execution_strategy.evidence_plan.search_queries else 'none'}

## Reference Skills (for style and pattern, not mandatory)
{_format_skill_reference(skills)}

## Available Data
{_summarize_payload(payload)}

## Output Requirements
- Generate self-contained Python code that satisfies ALL constraints above.
- Write artifacts to the output root declared above.
- Read input data from the mounts described in Available Data.
- Include error handling for missing files or malformed data.
- Print a JSON summary to stdout when done, including a "status" field and
  a "generated_artifacts" list with {{"key", "file_name", "path", "summary"}} entries.
"""
