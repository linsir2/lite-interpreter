"""
Router 意图路由节点

作用：
1. 基于结构化信号（意图结构 + 时效性 + 外部知识域）判断走静态还是动态
2. 明显开放（无本地数据 + 命中动态意图信号）→ dynamic_swarm
3. 其余一切默认走静态 → analyst（由 analyst 决定 capability_tier）
"""

from __future__ import annotations

from typing import Any

from src.blackboard.global_blackboard import global_blackboard
from src.blackboard.schema import GlobalStatus
from src.blackboard.task_state_services import ExecutionStateService
from src.common.contracts import ExecutionIntent
from src.common.logger import get_logger
from src.dag_engine.graphstate import DagGraphState
from src.memory import MemoryService
from src.runtime.analysis_runtime import _network_forbidden

logger = get_logger(__name__)

# 三层信号检测，替代前版 8 个硬编码领域关键词。
# 设计原则：不靠穷举领域词，而是识别查询的结构特征。
# 漏判后果可控——漏判的查询走 START_FROM_STATIC，analyst 仍可判为 dynamic。

# 第 1 层：探索性意图动词——查询明确要求研究/分析而非简单计算
_EXPLORATION_VERBS = (
    "研究", "调研", "分析报告", "行业分析", "对比分析",
    "综合评估", "多维度", "深度", "盘点", "扫描",
    "全景", "格局", "产业链", "生态",
)

# 第 2 层：时效性信号——查询依赖当前/最新信息，本地数据大概率过时
_TIMELINESS_SIGNALS = (
    "最新", "当前", "最近", "实时", "今年",
    "本月", "本周", "今日", "刚刚", "出炉",
    "2025", "2026",
)

# 第 3 层：外部知识域——查询主题天然需要外部信息源
# 注意：不含 "市场" 和 "趋势"——它们在本地分析上下文（市场份额、趋势图）中太容易误匹配。
# 更具体的 "行情""走势""供需""产能" 等替代了 "市场"；"走向" 替代了 "趋势"。
_EXTERNAL_DOMAIN_SIGNALS = (
    # 政策法规
    "政策", "法规", "监管", "合规", "条例", "办法", "通知",
    # 市场与经济（用更具体的术语替代 "市场" 和 "趋势"）
    "经济", "走向", "行情", "价格", "走势",
    "宏观", "微观", "供需", "产能", "库存",
    # 国际与竞品
    "国际", "全球", "海外", "进口", "出口", "贸易",
    "竞品", "对标", "benchmark", "对手", "竞争",
    # 金融
    "利率", "汇率", "CPI", "GDP", "PMI", "通胀", "加息",
    "降息", "股市", "期货", "债券",
)

# 所有信号扁平化用于匹配
_ALL_DYNAMIC_SIGNALS = _EXPLORATION_VERBS + _TIMELINESS_SIGNALS + _EXTERNAL_DOMAIN_SIGNALS


def _has_local_data(exec_data: Any) -> bool:
    inputs = getattr(exec_data, "inputs", None)
    has_dataset = bool(getattr(inputs, "structured_datasets", None) or [])
    has_docs = bool(getattr(inputs, "business_documents", None) or [])
    return has_dataset or has_docs


def _has_dynamic_intent(query: str) -> bool:
    """检测查询是否具有明确的动态探索意图。

    三层信号任一层命中即视为有动态意图。
    这种 OR 组合保证了覆盖面：即使某个领域词不在名单里，
    只要查询用了探索性动词或时效性词，仍能被识别。
    """
    lowered = str(query or "").lower()
    return any(s in lowered for s in _ALL_DYNAMIC_SIGNALS)


def _resolve_routing(query: str, exec_data: Any) -> ExecutionIntent:
    if _network_forbidden(query):
        return ExecutionIntent(
            intent="static_flow",
            destinations=["analyst"],
            reason="检测到禁止联网约束，强制走静态路径",
        )

    # 明显开放：无本地数据 + 查询有动态探索意图 → 走动态链
    if not _has_local_data(exec_data) and _has_dynamic_intent(query):
        return ExecutionIntent(
            intent="dynamic_flow",
            destinations=["dynamic_swarm"],
            reason="无本地数据且查询意图明显需要动态探索",
        )

    # 其余一切默认走静态链，由 analyst 决定 capability tier
    # 注意：有本地数据也走这里——不是跳过 analyst，而是让 analyst 判 capability_tier
    return ExecutionIntent(
        intent="static_flow",
        destinations=["analyst"],
        reason="走静态分析路径，由 analyst 决策 capability_tier",
    )


def router_node(state: DagGraphState) -> dict[str, Any]:
    tenant_id = state["tenant_id"]
    task_id = state["task_id"]
    query = state["input_query"]

    logger.info(f"[Router] 开始评估任务: {task_id}")

    global_blackboard.update_global_status(
        task_id=task_id,
        new_status=GlobalStatus.ROUTING,
        sub_status="正在评估任务需求与数据状态",
    )

    exec_data = ExecutionStateService.load(tenant_id, task_id)
    if not exec_data:
        raise ValueError(f"严重错误：找不到任务 {task_id} 的 ExecutionData")

    execution_intent = _resolve_routing(query, exec_data)
    ExecutionStateService.update_control(
        tenant_id=tenant_id,
        task_id=task_id,
        execution_intent=execution_intent,
    )

    return {
        "next_actions": list(execution_intent.destinations),
        "execution_intent": execution_intent.model_dump(mode="json"),
    }


def route_condition(state: DagGraphState) -> list[str]:
    """
    交通警察（Conditional Edge Callable）：
    供 LangGraph 图组装时使用，动态读取 Router 节点决定的下一步走向。
    """
    return state["next_actions"]
