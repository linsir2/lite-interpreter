"""Prompt templates used by the data inspector."""
from __future__ import annotations

DATA_INSPECTOR_SYSTEM_PROMPT = (
    "你是数据文件结构探查助手。"
    "你的职责是根据损坏或复杂的文件头文本，推断真实表结构，并给出可执行的 Pandas 读取建议。"
    "回答必须简洁、结构化、偏工程实现。"
)


def build_llm_fallback_prompt(head_text: str) -> str:
    return f"""
这是一个解析失败的数据文件头部（前50行）：
```text
{head_text}
```

请你：
1. 推断真实表头和字段分组。
2. 识别可能的分隔符、编码、跳过行数。
3. 给出最小可执行的 Pandas `read_csv` 参数建议。

请严格按以下格式输出：

【表头推断】
- ...

【读取建议】
```python
kwargs = {{
    "skiprows": 0,
    "sep": ",",
    "encoding": "utf-8"
}}
```
""".strip()
