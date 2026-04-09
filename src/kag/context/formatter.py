"""将压缩后的候选片段格式化为业务上下文。"""

from __future__ import annotations


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
            if any(keyword in lower_text for keyword in ["规则", "标准", "合规", "流程"]):
                context["rules"].append(text)
            if any(keyword in lower_text for keyword in ["指标", "口径", "ratio", "rate", "metric"]):
                context["metrics"].append(text)
            if any(keyword in lower_text for keyword in ["过滤", "条件", "范围", "筛选"]):
                context["filters"].append(text)
            context["sources"].append(source)
            markdown_parts.append(f"### 证据 {index}\n- 来源: {source}\n- 通道: {retrieval_type}\n- 内容: {text}")
        context["sources"] = sorted(set(context["sources"]))
        return context, "\n\n".join(markdown_parts)
