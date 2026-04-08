"""
严格状态白名单说明。

这份白名单的目标不是为“继续随便加 dict 字段”开绿灯，而是显式记录：
- 哪些自由结构目前是有意保留的
- 为什么保留
- 未来如果继续收敛，优先应该收哪一层

这样后续审查时，才能区分：
- 合法扩展口
- 还没收完的技术债
- 真正的设计倒退
"""
from __future__ import annotations

from typing import Any


def build_strict_state_report() -> dict[str, Any]:
    return {
        "strict_state_enabled": True,
        "core_typed_state_surfaces": [
            "TaskEnvelope",
            "ExecutionIntent",
            "ExecutionRecord",
            "StructuredDatasetState",
            "BusinessDocumentState",
            "BusinessContextState",
            "KnowledgeSnapshotState",
            "KnowledgeSnapshotMetadataState",
            "DynamicTraceEventState",
            "RuntimeMetadataState",
            "InputMountState",
            "AuditResultState",
            "DynamicRequestRuntimeState",
            "DynamicRequestState",
            "SkillPayloadState",
            "HistoricalSkillMatchState",
            "ReplayCaseState",
            "SkillValidationState",
            "SkillPromotionState",
            "SkillProvenanceState",
            "SkillUsageState",
            "SkillMetadataState",
            "SkillAuthorizationState",
            "SkillRecommendedState",
            "TaskMemorySummaryState",
            "WorkspacePreferenceState",
            "MemoryCacheHintState",
            "MemoryData",
            "NodeCheckpointState",
            "NodeOutputPatchState",
        ],
        "allowed_flexible_fields": [
            {
                "field": "KnowledgeSnapshotState.hits[*]",
                "reason": "检索命中文档片段结构仍受底层召回通道差异影响，当前保留原样片段字典",
            },
            {
                "field": "KnowledgeSnapshotState.filters",
                "reason": "查询理解输出的过滤条件仍是半结构化表达，短期保留自由键值",
            },
            {
                "field": "DynamicTraceEventState.tool_call",
                "reason": "不同 runtime/tool 事件载荷差异较大，当前只约束公共外壳",
            },
            {
                "field": "DynamicTraceEventState.payload",
                "reason": "保留原始 runtime 事件上下文，便于调试与前端回放",
            },
            {
                "field": "SkillMetadataState.<extra>",
                "reason": "技能元数据仍允许少量实验性扩展键，但稳定字段已收敛为 summary/source/trace_count/match_source/recommended/authorization",
            },
            {
                "field": "ReplayCaseState.metadata",
                "reason": "不同 replay case 可能携带不同的验证上下文，暂未统一成更细粒度子模型",
            },
            {
                "field": "WorkspacePreferenceState.value",
                "reason": "workspace 偏好值允许是标量、列表或轻量字典，当前保留开放值类型",
            },
            {
                "field": "MemoryCacheHintState.metadata",
                "reason": "cache hint 只保留少量诊断附加键，不把完整缓存响应纳入 memory plane",
            },
            {
                "field": "NodeOutputPatchState.<extra>",
                "reason": "checkpoint 仍允许少量罕见节点输出字段透传，但常见恢复关键字段已建模",
            },
            {
                "field": "NodeOutputPatchState.final_response",
                "reason": "最终回复面向 UI 与用户展示，保持开放字典以兼容展示层演进",
            },
            {
                "field": "DynamicRequestState.system_context",
                "reason": "动态上下文仍承载约束、知识快照和执行快照等协议化内容，当前保留为开放字典",
            },
            {
                "field": "DynamicRequestState.metadata",
                "reason": "动态运行时 metadata 仍允许后端协议附加少量运行诊断键",
            },
        ],
        "next_strict_targets": [
            "KnowledgeSnapshotState.hits[*]",
            "DynamicTraceEventState.tool_call",
            "DynamicRequestState.system_context",
            "WorkspacePreferenceState.value",
        ],
    }
