"""Native LLM tool-calling exploration loop.

Replaces the DeerFlow sidecar with an in-process exploration loop
that consumes MCP gateway tools via LiteLLM function-calling.

Design:
  - One tool call per round (lightweight, no batch plans)
  - Each step recorded as ExplorationStep for future skill solidification
  - Sandbox is for temporary computation only; heavy analysis is deferred
    to the static chain (coder → executor)
  - Loop stops when LLM outputs a final answer or the step budget is exhausted
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel, Field

from src.common import get_logger

logger = get_logger(__name__)

_RECOVERABLE_EXCEPTIONS = (ImportError, ModuleNotFoundError, ConnectionError, TimeoutError, OSError)

# Internal infrastructure tools not exposed to the exploration loop
_EXCLUDED_TOOLS = {"dynamic_trace", "memory_sync", "skill_auth"}

# ── OpenAI function-calling parameter schemas ──────────────────────────
_TOOL_PARAM_SCHEMAS: dict[str, dict[str, Any]] = {
    "web_search": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query (Chinese or English)"},
        },
        "required": ["query"],
    },
    "web_fetch": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to fetch and extract text from"},
        },
        "required": ["url"],
    },
    "knowledge_query": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Natural language query for local knowledge graph"},
            "top_k": {"type": "integer", "description": "Max results (default 8)"},
        },
        "required": ["query"],
    },
    "sandbox_exec": {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": (
                    "Python code for TEMPORARY computation only (quick validation, "
                    "small aggregation, data transformation). Do NOT generate final "
                    "report code here — that belongs to the static chain."
                ),
            },
        },
        "required": ["code"],
    },
}


# ── Models ──────────────────────────────────────────────────────────────

class ExplorationStep(BaseModel):
    """One tool-call step in the exploration loop, recorded for skill solidification."""

    step_index: int
    tool_name: str
    tool_args: dict[str, Any] = Field(default_factory=dict)
    tool_result_summary: str = ""
    rationale: str = ""
    observation: str = ""
    decision: str = ""
    success: bool = True
    error: str | None = None
    structured_result: dict[str, Any] | None = None
    raw_result: str | None = None


@dataclass
class ExplorationResult:
    """Output of one exploration loop invocation."""

    summary: str = ""
    steps: list[ExplorationStep] = field(default_factory=list)
    trace_events: list[dict[str, Any]] = field(default_factory=list)
    continuation: str = "finish"
    next_static_steps: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    suggested_static_actions: list[str] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)
    external_knowledge: list[dict[str, Any]] = field(default_factory=list)

    def to_overlay(self) -> Any:
        from src.common.control_plane import ensure_dynamic_resume_overlay

        return ensure_dynamic_resume_overlay({
            "continuation": self.continuation,
            "next_static_steps": self.next_static_steps,
            "evidence_refs": self.evidence_refs,
            "open_questions": self.open_questions,
            "suggested_static_actions": self.suggested_static_actions,
            "external_knowledge": self.external_knowledge,
        })

    def to_state_patch(self) -> dict[str, Any]:
        overlay = self.to_overlay()
        return {
            "dynamic_status": "completed",
            "dynamic_summary": self.summary,
            "dynamic_continuation": overlay.continuation,
            "dynamic_resume_overlay": overlay.model_dump(mode="json"),
            "dynamic_next_static_steps": list(overlay.next_static_steps),
            "dynamic_trace": [],
            "dynamic_artifacts": [],
            "recommended_static_skill": None,
            "dynamic_runtime_metadata": {
                "effective_runtime_mode": "native",
                "requested_runtime_mode": "native",
            },
        }


# ── System prompt ───────────────────────────────────────────────────────

def _build_exploration_system_prompt(tool_descriptions: str) -> str:
    return f"""You are a research analyst performing multi-step dynamic exploration.

## Tools
{tool_descriptions}

## How to work
- At each step, choose ONE tool to call. Do NOT output a batch plan — act one step at a time.
- After seeing the tool result, observe what you learned and decide the next step.
- web_search is for broad queries, web_fetch is for reading a specific page.
- sandbox_exec is for LIGHTWEIGHT temporary computation only (quick validation,
  small aggregation, data transformation). Heavy analysis that produces user
  deliverables MUST be left for the static chain — do NOT write final report code here.

## When to stop
- You have gathered enough information to answer the research question → output final answer.
- The information cannot be found despite reasonable effort → output final answer with open_questions.
- You are running low on steps → synthesize what you have found so far.

## Final answer format (when done exploring)
### Summary
Concise findings in natural language.

### Open Questions
Bullet list of questions you could not answer.

### Next Steps
Suggested static analysis actions (comma-separated from: analyst, coder, evidence_collection) or "none".

### Evidence References
List of URLs or source identifiers you found and used."""


# ── Tool schema builders ────────────────────────────────────────────────

def _build_tool_schemas(allowed_tools: list[str]) -> list[dict[str, Any]]:
    """Build OpenAI function-calling tool schemas from MCP gateway tools."""
    from src.mcp_gateway.mcp_server import default_mcp_server

    available = default_mcp_server.list_tools()
    schemas: list[dict[str, Any]] = []
    for tool_meta in available:
        name = tool_meta["name"]
        if name in _EXCLUDED_TOOLS:
            continue
        if allowed_tools and name not in allowed_tools:
            continue
        param_schema = _TOOL_PARAM_SCHEMAS.get(name, {"type": "object", "properties": {}})
        schemas.append({
            "type": "function",
            "function": {
                "name": name,
                "description": tool_meta["description"],
                "parameters": param_schema,
            },
        })
    return schemas


def _build_tool_description_list(allowed_tools: list[str]) -> str:
    """Build a human-readable tool description list for the system prompt."""
    from src.mcp_gateway.mcp_server import default_mcp_server

    available = default_mcp_server.list_tools()
    lines: list[str] = []
    for tool_meta in available:
        name = tool_meta["name"]
        if name in _EXCLUDED_TOOLS:
            continue
        if allowed_tools and name not in allowed_tools:
            continue
        param_schema = _TOOL_PARAM_SCHEMAS.get(name, {"type": "object", "properties": {}})
        props = param_schema.get("properties", {})
        required = param_schema.get("required", [])
        param_strs = [f"{p}{'*' if p in required else ''}" for p in props]
        lines.append(f"- **{name}**({'|'.join(param_strs)}): {tool_meta['description']}")
    return "\n".join(lines)


# ── Helpers ─────────────────────────────────────────────────────────────

def _call_tool_safe(name: str, args: dict[str, Any], context: dict[str, Any]) -> tuple[Any, str | None]:
    """Execute a tool call. Returns (result, error_message)."""
    from src.mcp_gateway.mcp_server import default_mcp_server

    try:
        result = default_mcp_server.call_tool(name, arguments=args, context=context)
        return result, None
    except Exception as exc:
        logger.warning(f"[ExplorationLoop] tool '{name}' failed: {exc}")
        return None, str(exc)


def _describe_tool_result(result: Any, raw_str: str) -> str:
    """Describe a tool result semantically instead of hard-truncating."""
    if result is None:
        return "(no result)"
    if isinstance(result, dict):
        items = result.get("items") or result.get("results") or result.get("records") or []
        if isinstance(items, list) and items:
            return f"Found {len(items)} results"
        keys = list(result.keys())[:10]
        return f"Result with keys: {', '.join(keys)}"
    if isinstance(result, list):
        return f"List with {len(result)} items"
    if isinstance(result, str):
        return f"Text result ({len(result)} chars)"
    return f"Result of type {type(result).__name__}"


def _truncate_result(result: Any, max_chars: int = 2000) -> str:
    """Truncate tool result for step recording and LLM context."""
    if result is None:
        return "(no result)"
    text = json.dumps(result, ensure_ascii=False, default=str)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"... [truncated, total {len(text)} chars]"


def _summary_from_structured(structured) -> str:
    """Generate a compact structured summary from ExternalKnowledge for LLM context."""
    kind = getattr(structured, "kind", None) or "textual_finding"
    if kind == "lookup_table":
        name = getattr(structured, "table_name", "") or "unknown"
        rows = len(getattr(structured, "rows", []) or [])
        cols = getattr(structured, "columns", []) or []
        return f"[Structured:{kind}] table_name={name}, rows={rows}, columns={cols}"
    if kind == "numeric_fact":
        entity = getattr(structured, "entity", "")
        metric = getattr(structured, "metric", "")
        value = getattr(structured, "value", None)
        unit = getattr(structured, "unit", "")
        period = getattr(structured, "period", "")
        return f"[Structured:{kind}] entity={entity}, metric={metric}, value={value}, unit={unit}, period={period}"
    # textual_finding
    topic = getattr(structured, "topic", "") or ""
    summary = getattr(structured, "summary", "") or ""
    return f"[Structured:{kind}] topic={topic}, summary={summary}"


def _extract_external_knowledge(steps: list[ExplorationStep]) -> list[dict[str, Any]]:
    """Aggregate structured results from exploration steps."""
    return [s.structured_result for s in steps if s.structured_result]


def _parse_final_answer(content: str, default_continuation: str) -> dict[str, Any]:
    """Extract structured fields from the LLM's final answer."""
    open_questions: list[str] = []
    next_steps: list[str] = []
    evidence_refs: list[str] = []
    sections = {"open questions": 0, "next steps": 0, "evidence references": 0}

    current_section: str | None = None
    for line in content.split("\n"):
        stripped = line.strip()
        lowered = stripped.lower().lstrip("#").strip()

        if lowered.startswith("open questions"):
            current_section = "open_questions"
            continue
        if lowered.startswith("next steps"):
            current_section = "next_steps"
            continue
        if lowered.startswith("evidence references"):
            current_section = "evidence_refs"
            continue
        if stripped.startswith("###") or stripped.startswith("##"):
            current_section = None
            continue

        if current_section == "open_questions" and (stripped.startswith("-") or stripped.startswith("*")):
            text = stripped.lstrip("-* ").strip()
            if text:
                open_questions.append(text)
        elif current_section == "next_steps":
            if "none" in lowered:
                next_steps = []
            else:
                for step in ("analyst", "coder", "evidence_collection"):
                    if step in lowered:
                        next_steps.append(step)
        elif current_section == "evidence_refs" and (stripped.startswith("-") or stripped.startswith("*")):
            text = stripped.lstrip("-* ").strip()
            if text and (text.startswith("http") or text.startswith("www")):
                evidence_refs.append(text)

    return {
        "open_questions": open_questions,
        "next_static_steps": list(dict.fromkeys(next_steps)),
        "evidence_refs": evidence_refs,
        "continuation": default_continuation,
    }


# ── Main loop ───────────────────────────────────────────────────────────

def run_exploration_loop(
    *,
    query: str,
    context: dict[str, Any],
    allowed_tools: list[str],
    max_steps: int = 6,
    continuation_default: str = "finish",
    on_event: Callable[[dict[str, Any]], None] | None = None,
) -> ExplorationResult:
    """Run the native LLM tool-calling exploration loop.

    Args:
        query: The research question.
        context: Tenant/task/workspace context dict for tool execution.
        allowed_tools: Tool names the LLM may use.
        max_steps: Maximum number of tool-call rounds.
        continuation_default: "finish" (dynamic-only) or "resume_static".
        on_event: Callback for each trace event emitted during exploration.

    Returns:
        ExplorationResult with summary, step records, and overlay fields.
    """
    from src.common.llm_client import LiteLLMClient

    tools = _build_tool_schemas(allowed_tools)
    if not tools:
        logger.warning("[ExplorationLoop] No tools available")
        return ExplorationResult(
            summary="No exploration tools available for this task.",
            continuation=continuation_default,
        )

    tool_descriptions = _build_tool_description_list(allowed_tools)
    system_prompt = _build_exploration_system_prompt(tool_descriptions)

    knowledge = json.dumps(context.get("knowledge_snapshot") or {}, ensure_ascii=False, default=str)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                f"Research task: {query}\n\n"
                f"Local knowledge (for reference): {knowledge}\n\n"
                f"You may use up to {max_steps} tool calls. Begin exploration."
            ),
        },
    ]

    steps: list[ExplorationStep] = []
    trace_events: list[dict[str, Any]] = []
    consecutive_failures = 0

    for step_idx in range(max_steps):
        # ── LLM call ────────────────────────────────────────────────
        try:
            response = LiteLLMClient.completion(
                alias="reasoning_model",
                messages=messages,
                tools=tools,
                tool_choice="auto",
                max_tokens=4096,
            )
        except _RECOVERABLE_EXCEPTIONS as exc:
            logger.error(f"[ExplorationLoop] LLM unavailable at step {step_idx}: {exc}")
            trace_events.append({
                "event_type": "error",
                "message": f"LLM unavailable at step {step_idx}: {exc}",
            })
            return ExplorationResult(
                summary=f"Exploration interrupted: LLM unavailable at step {step_idx}.",
                steps=steps,
                trace_events=trace_events,
                continuation=continuation_default,
                external_knowledge=_extract_external_knowledge(steps),
            )

        msg = response["choices"][0]["message"]

        # ── No tool_calls → final answer ──────────────────────────
        if not msg.get("tool_calls"):
            content = str(msg.get("content") or "").strip()
            structured = _parse_final_answer(content, continuation_default)
            trace_events.append({"event_type": "done", "step": step_idx})
            if on_event:
                on_event(trace_events[-1])
            ek = _extract_external_knowledge(steps)
            return ExplorationResult(
                summary=content,
                steps=steps,
                trace_events=trace_events,
                continuation=structured["continuation"],
                next_static_steps=structured["next_static_steps"],
                evidence_refs=structured["evidence_refs"],
                open_questions=structured["open_questions"],
                findings=ek,
                external_knowledge=ek,
            )

        # ── Process tool calls (one at a time) ─────────────────────
        messages.append({
            "role": "assistant",
            "content": msg.get("content"),
            "tool_calls": msg["tool_calls"],
        })

        for tool_call in msg["tool_calls"]:
            tool_name = str(tool_call["function"]["name"])
            try:
                tool_args = json.loads(tool_call["function"]["arguments"])
            except json.JSONDecodeError:
                tool_args = {}

            if on_event:
                on_event({
                    "event_type": "tool_call_start",
                    "tool_name": tool_name,
                    "arguments": tool_args,
                    "step": step_idx,
                })

            result, error = _call_tool_safe(tool_name, tool_args, context)
            raw_str = json.dumps(result, ensure_ascii=False, default=str) if result is not None else ""

            # Structure web results inline (ADR-005 Phase 2)
            structured = None
            summary = _describe_tool_result(result, raw_str)
            if result is not None and not error and tool_name in ("web_search", "web_fetch"):
                try:
                    from src.compiler.evidence_structurer import structure_external_evidence

                    url = str(tool_args.get("url", ""))
                    structured = structure_external_evidence(raw_text=raw_str, url=url)
                except Exception:
                    structured = None
                if structured is not None:
                    summary = _summary_from_structured(structured)

            # Send structured summary to LLM (not truncated raw text)
            tool_content: dict[str, Any] = {"error": error} if error else {"summary": summary}
            if structured is not None:
                tool_content["structured_result"] = structured.model_dump(mode="json")
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "content": json.dumps(tool_content, ensure_ascii=False),
            })

            steps.append(ExplorationStep(
                step_index=step_idx,
                tool_name=tool_name,
                tool_args=tool_args,
                tool_result_summary=summary,
                success=error is None,
                error=error,
                structured_result=structured.model_dump(mode="json") if structured else None,
                raw_result=raw_str or None,
            ))

            trace_entry: dict[str, Any] = {
                "event_type": "tool_result",
                "tool_name": tool_name,
                "success": error is None,
                "step": step_idx,
            }
            if error:
                trace_entry["error"] = error
            trace_events.append(trace_entry)
            if on_event:
                on_event(trace_entry)

            if error:
                consecutive_failures += 1
            else:
                consecutive_failures = 0

        # ── Consecutive failures check ─────────────────────────────
        if consecutive_failures >= 3:
            logger.warning("[ExplorationLoop] Too many consecutive failures, stopping")
            return ExplorationResult(
                summary="Exploration stopped: tools failed repeatedly.",
                steps=steps,
                trace_events=trace_events,
                continuation=continuation_default,
                open_questions=["Exploration terminated due to repeated tool failures"],
                external_knowledge=_extract_external_knowledge(steps),
            )

    # ── Step budget exhausted → force summarization ─────────────────
    try:
        messages.append({
            "role": "user",
            "content": "You have reached the step limit. Summarize your findings using the required format (### Summary / ### Open Questions / ### Next Steps / ### Evidence References).",
        })
        final_response = LiteLLMClient.completion(alias="reasoning_model", messages=messages, max_tokens=2048)
        final_content = str(final_response["choices"][0]["message"].get("content") or "").strip()
    except _RECOVERABLE_EXCEPTIONS:
        final_content = f"Exploration stopped after {max_steps} steps (LLM unavailable for summary)."

    structured = _parse_final_answer(final_content, continuation_default)
    trace_events.append({"event_type": "done", "step": max_steps, "budget_exhausted": True})
    if on_event:
        on_event(trace_events[-1])

    ek = _extract_external_knowledge(steps)
    return ExplorationResult(
        summary=final_content,
        steps=steps,
        trace_events=trace_events,
        continuation=structured["continuation"],
        next_static_steps=structured["next_static_steps"],
        evidence_refs=structured["evidence_refs"],
        open_questions=structured["open_questions"],
        findings=ek,
        external_knowledge=ek,
    )
