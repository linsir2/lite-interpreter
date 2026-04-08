# Strict State Whitelist

这份文档记录 lite-interpreter 当前“严格状态”下，哪些字段已经被收敛成显式 schema，哪些字段仍然被允许保持一定自由度。

目的不是给自由结构背书，而是建立一条明确边界：

- 什么属于已经类型化的核心状态
- 什么属于暂时允许的扩展口
- 下一步如果继续收敛，优先应该收哪里

## 1. 已类型化的核心状态

当前黑板核心状态里，以下结构已经是显式模型：

- `TaskEnvelope`
- `ExecutionIntent`
- `ExecutionRecord`
- `StructuredDatasetState`
- `BusinessDocumentState`
- `BusinessContextState`
- `KnowledgeSnapshotState`
- `KnowledgeSnapshotMetadataState`
- `DynamicTraceEventState`
- `RuntimeMetadataState`
- `InputMountState`
- `AuditResultState`
- `DynamicRequestRuntimeState`
- `DynamicRequestState`
- `SkillPayloadState`
- `HistoricalSkillMatchState`
- `ReplayCaseState`
- `SkillValidationState`
- `SkillPromotionState`
- `SkillProvenanceState`
- `SkillUsageState`
- `SkillMetadataState`
- `SkillAuthorizationState`
- `SkillRecommendedState`
- `NodeCheckpointState`
- `NodeOutputPatchState`

## 2. 允许保持自由结构的字段

这些字段目前仍允许部分自由键值，但这是显式白名单，不应继续无限扩张。

### 2.1 知识检索面

- `KnowledgeSnapshotState.hits[*]`
  原因：不同召回通道返回的片段结构还不完全统一。

- `KnowledgeSnapshotState.filters`
  原因：查询理解产出的 filter 还属于半结构化表达。

### 2.2 动态轨迹面

- `DynamicTraceEventState.tool_call`
  原因：不同 runtime/tool 的事件结构差异还很大。

- `DynamicTraceEventState.payload`
  原因：这里保留原始 runtime 事件上下文，服务于调试、回放和资源化派生。

### 2.3 技能面

- `SkillMetadataState.<extra>`
  原因：仍允许少量实验性 metadata 扩展键。

- `ReplayCaseState.metadata`
  原因：不同 replay case 可能携带不同验证上下文。

### 2.4 恢复面

- `NodeOutputPatchState.<extra>`
  原因：checkpoint 仍允许少量罕见节点输出字段透传。

- `DynamicRequestState.system_context`
  原因：动态上下文承载约束、知识快照、执行快照等协议化内容，当前保留开放字典。

- `DynamicRequestState.metadata`
  原因：动态运行时 metadata 仍允许少量后端诊断扩展键。

- `NodeOutputPatchState.final_response`
  原因：最终回复面向 UI 与展示层，保留一定开放性。

## 3. 下一步建议优先收紧的目标

如果继续做严格状态收敛，优先顺序建议是：

1. `KnowledgeSnapshotState.hits[*]`
2. `DynamicTraceEventState.tool_call`
3. `DynamicRequestState.system_context`

这些字段一旦收掉，黑板核心状态就会进一步接近“只剩明确扩展点”的状态。
