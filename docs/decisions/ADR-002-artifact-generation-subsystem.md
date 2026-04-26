# ADR-002: Promote artifact generation to a first-class static-chain subsystem

## Status

Accepted

## Date

2026-04-23

## Context

旧静态链的成功条件更接近：

- 代码生成成功
- AST 审计通过
- 能打印结构化 JSON

但这并不等于用户真正拿到了稳定交付物。

## Decision

把 artifact generation 和 artifact verification 提升为 static chain 的正式子系统。

当前 v1 做法：

- family generator 显式声明 artifact contract
- executor 后验证 required artifact
- summarizer 先组织用户交付物，再组织内部诊断

## Alternatives Considered

### 维持“JSON first”，由前端自己解释结果

- Pros: 后端改动少
- Cons: 用户交付物语义继续漂移到前端
- Rejected: 违背 app-facing API 的 server-built projection 方向

### 直接引入重型图表引擎

- Pros: 可以更快生成漂亮图表
- Cons: 依赖和运行时复杂度明显上升
- Rejected: v1 先保证报告和导出稳定

## Consequences

- `ExecutionRecord` 之后多了一层 artifact verification
- “代码安全但没产交付物”不再算成功
- generator registry 成为长期演进边界
