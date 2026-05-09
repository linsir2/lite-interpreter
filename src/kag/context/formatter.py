"""将压缩后的候选片段格式化为业务上下文。"""

from __future__ import annotations

from src.compiler.kag import KnowledgeCompilerService


class ContextFormatter:
    @classmethod
    def format(cls, candidates: list[dict[str, object]]) -> tuple[dict[str, list[str]], str]:
        context = {"rules": [], "metrics": [], "filters": [], "sources": []}
        markdown_parts: list[str] = []
        for index, candidate in enumerate(candidates, start=1):
            text = str(candidate.get("compressed_text") or candidate.get("text") or "").strip()
            if not text:
                continue
            source = str(candidate.get("source", "unknown"))
            retrieval_type = str(candidate.get("retrieval_type", "text"))
            lower_text = text.lower()
            lexical_signals = KnowledgeCompilerService.match_text(text)
            lexical_entities = [match.canonical for match in lexical_signals if match.category == "entity"]
            rule_spec = KnowledgeCompilerService.parse_rule(text)
            metric_spec = KnowledgeCompilerService.parse_metric(text)
            filter_spec = KnowledgeCompilerService.parse_filter(text)
            if lexical_entities and (not hasattr(rule_spec, "error_code")) and (
                any(keyword in lower_text for keyword in ["规则", "标准", "合规", "流程"]) or getattr(rule_spec, "required_terms", [])
            ):
                context["rules"].append(text)
            if lexical_entities and (not hasattr(metric_spec, "error_code")) and (
                any(keyword in lower_text for keyword in ["指标", "口径", "ratio", "rate", "metric"])
                or getattr(metric_spec, "metric_name", "")
            ):
                context["metrics"].append(text)
            if not hasattr(filter_spec, "error_code") and (
                any(keyword in lower_text for keyword in ["过滤", "条件", "范围", "筛选"]) or getattr(filter_spec, "field", "")
            ):
                context["filters"].append(text)
            context["sources"].append(source)
            markdown_parts.append(f"### 证据 {index}\n- 来源: {source}\n- 通道: {retrieval_type}\n- 内容: {text}")
        context["sources"] = sorted(set(context["sources"]))
        return context, "\n\n".join(markdown_parts)
