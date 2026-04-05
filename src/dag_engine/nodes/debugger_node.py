"""Minimal debugger node that rewrites code into a safe fallback after audit failure."""
from __future__ import annotations

import json
from typing import Any, Dict

from src.blackboard.execution_blackboard import execution_blackboard
from src.blackboard.global_blackboard import global_blackboard
from src.blackboard.schema import GlobalStatus
from src.common import get_logger
from src.dag_engine.graphstate import DagGraphState

logger = get_logger(__name__)


def debugger_node(state: DagGraphState) -> Dict[str, Any]:
    tenant_id = state["tenant_id"]
    task_id = state["task_id"]

    global_blackboard.update_global_status(
        task_id=task_id,
        new_status=GlobalStatus.DEBUGGING,
        sub_status="正在回退到安全调试版本代码",
    )

    exec_data = execution_blackboard.read(tenant_id, task_id)
    if not exec_data:
        logger.warning(f"[Debugger] 缺少任务 {task_id} 的执行上下文")
        return {"generated_code": "", "next_actions": ["auditor"], "retry_count": 1}

    payload = json.dumps(
        {
            "query": state["input_query"],
            "status": "debugger_fallback",
            "error": exec_data.latest_error_traceback or "audit failed",
        },
        ensure_ascii=False,
    )
    exec_data.generated_code = (
        "import json\n"
        f"payload = json.loads({payload!r})\n"
        "print(json.dumps(payload, ensure_ascii=False))\n"
    )
    retry_count = int(state.get("retry_count", 0) or 0) + 1
    execution_blackboard.write(tenant_id, task_id, exec_data)
    execution_blackboard.persist(tenant_id, task_id)
    return {"generated_code": exec_data.generated_code, "next_actions": ["auditor"], "retry_count": retry_count}
