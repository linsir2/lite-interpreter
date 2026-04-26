# ADR-003: Deprecate legacy static-generation control fields through dual-write cutover

## Status

Accepted

## Date

2026-04-23

## Context

旧静态链仍有一组高耦合 legacy 字段：

- `analysis_plan`
- `generation_directives`
- `next_static_steps`
- `dynamic_next_static_steps`
- `build_dataset_aware_code`
- `static_codegen_renderer`

这些对象已经广泛存在于：

- 恢复链路
- 动态 -> 静态 handoff
- summarizer 细节输出
- 测试断言

## Decision

不做一轮硬删。

采用：

1. inventory
2. dual-write
3. reader cutover
4. zero-active-dependency proof
5. final removal

## Alternatives Considered

### 一轮内直接删除旧字段

- Pros: 表面上更干净
- Cons: 风险高，回放和恢复链路容易断
- Rejected: 不符合当前仓库迁移阶段

### 永久保留旧字段

- Pros: 最省事
- Cons: 两套真相会长期共存
- Rejected: 与仓库收口目标冲突

## Legacy Inventory Appendix

| Object | Current Role | Compatibility Role | Removal Gate |
| --- | --- | --- | --- |
| `analysis_plan` | 展示辅助 | dual-write / read fallback | 展示层不再依赖它承载额外控制语义 |
| `generation_directives` | legacy renderer 输入 | adapter fallback | generator registry 稳定 |
| `next_static_steps` | dynamic -> static legacy step list | dual-write | `DynamicResumeOverlay` 成为唯一主语义 |
| `dynamic_next_static_steps` | graph patch 兼容字段 | dual-write | dynamic reader 全部切换 |
| `build_dataset_aware_code` | legacy codegen entry | fallback | family generator 稳定 |
| `static_codegen_renderer` | legacy template renderer | fallback | 新 registry 不再走主路径 |

## Consequences

- 迁移会更长，但可验证
- 旧字段仍然需要测试护栏
- 最终删除时能更容易证明“没有活跃读者”
