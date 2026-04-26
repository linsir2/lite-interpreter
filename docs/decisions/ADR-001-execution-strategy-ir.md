# ADR-001: Use ExecutionStrategy as the internal static-generation truth source

## Status

Accepted

## Date

2026-04-23

## Context

静态链原来的控制语义分散在：

- `analysis_plan`
- `generation_directives`
- `next_static_steps`
- renderer 内部隐式逻辑

这会导致两个问题：

1. 读路径和写路径很难判断“哪一处才是真正控制生成行为的字段”
2. artifact contract 无法成为正式的一等对象

## Decision

引入 `ExecutionStrategy`，作为静态链的内部主控制真相源。

它至少包含：

- `strategy_family`
- `artifact_plan`
- `verification_plan`
- `resume_overlay`
- `legacy_compatibility`

## Alternatives Considered

### 继续扩张 `analysis_plan`

- Pros: 改动最小
- Cons: 展示文案继续和主控制语义混在一起
- Rejected: 不能稳定承载 artifact contract

### 直接把所有控制语义塞进 `final_response.details`

- Pros: 前端调试时容易看到
- Cons: 这是执行后投影，不是执行时真相源
- Rejected: 会造成“总结结果反向控制执行”的倒置结构

## Consequences

- static chain 有了明确的内部策略对象
- dual-write 期间需要继续保留旧字段
- 后续 reader cutover 和 final removal 会更可验证
