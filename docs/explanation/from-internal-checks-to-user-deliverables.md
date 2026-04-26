# From Internal Checks to User Deliverables

这轮重构解决的是一个很具体的问题：

旧静态链会输出很多内部结构：

- `datasets`
- `documents`
- `rule_checks`
- `metric_checks`
- `filter_checks`
- `derived_findings`

这些内容对系统自己有用，但对最终用户并不等于“交付物”。

用户真正需要的是：

- 报告
- 对比导出
- 可下载的结构化结论

## 为什么旧方案不够

旧方案的问题不是前端不会展示，而是后端没有把 artifact 当成一等对象。

具体表现为：

- 成功条件更接近“代码能跑、JSON 能打印”
- 不是“交付物已经稳定产出”
- 前端 detail 页虽然能预览/下载，但后端没有稳定地告诉它“什么才是主结果”

## 这轮改变了什么

### 1. 把策略显式化

`ExecutionStrategy` 成为内部主控制真相源。

### 2. 把 artifact contract 显式化

每个 family 现在都声明：

- 要产什么
- 哪些是必选
- 执行后如何验证

### 3. 把成功条件抬高

现在不再接受“代码安全但没产交付物”的伪成功。

### 4. 把排序语义固定

summarizer 先组织用户交付物，再把内部诊断退到后面。

## 为什么 v1 还保留 legacy renderer

因为这次的目标是先收口 contract，不是同一轮把所有 family 内部实现全部重写。

所以 v1 的判断是：

- 先把 generator registry、artifact plan、verification plan 跑通
- 再逐步降低对 legacy dataset-aware renderer 的依赖
