# Legacy Removal Strategy

这轮不会直接删除旧字段。

原因很简单：当前仓库里仍然有很多地方把这些字段当作恢复链路或展示链路的一部分。

如果在同一轮里直接删掉：

- 会打断旧任务恢复
- 会让动态 -> 静态 handoff 丢失语义
- 会让 summarizer / tests / docs 一起失真

## 当前 reader cutover 顺序

1. 新字段先写入
2. 读路径优先读新字段
3. 旧字段只做 compatibility-only
4. 做 zero-active-dependency proof
5. 最后删除旧字段和旧断言

## 当前保留对象

- `analysis_plan`
- `generation_directives`
- `next_static_steps`
- `dynamic_next_static_steps`
- `build_dataset_aware_code`
- `static_codegen_renderer`

## 删除门槛

删除前必须同时满足：

- `ExecutionStrategy` 已成为唯一主控制真相源
- `DynamicResumeOverlay` 不再依赖 legacy step list 作为主语义
- generator registry 已稳定，legacy generator 不再是主路径
- DAG / runtime / summarizer / presenter 测试都已经切到新 contract

## 当前判断

最晚删除的是 `analysis_plan`。

原因不是它还负责控制，而是它仍然承担展示辅助职责。
