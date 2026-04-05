# lite-interpreter Runtime Support Matrix

这份文档用于说明当前不同执行模式和运行时在能力上的差异。

## 1. 当前运行时对象

当前系统里可以区分的执行面/运行时对象有：

- `static-chain`
  指 Router 命中静态链后，由 DAG 驱动的分析/代码生成/审计/执行路径
- `deerflow-sidecar`
  指 `runtime_mode=sidecar` 时的动态运行时
- `deerflow-embedded`
  指 `runtime_mode=embedded` 时的动态运行时
- `sandbox`
  指最终 Python 代码执行边界

## 2. 支持矩阵

| 能力 | static-chain | deerflow-sidecar | deerflow-embedded | sandbox |
| --- | --- | --- | --- | --- |
| DAG owner | Yes | No | No | No |
| Dynamic planning | No | Yes | Yes | No |
| Tool-mediated research | Limited | Yes | Yes | No |
| Final code execution | Via sandbox | No | No | Yes |
| Runtime streaming | Node-level | Yes | Yes | Limited |
| Artifact resource | Yes | Yes | Yes | Yes |
| Tool-call resource | Partial | Partial | Partial | No |
| Governance gating | Yes | Yes | Yes | Yes |
| Resume / attach stream | No | Yes | Yes | No |

## 3. 逐项解释

### static-chain

优点：

- 完整受 DAG 控制
- 与 blackboard、KAG、SkillNet、sandbox 边界清晰
- 最终状态和结果结构更稳定

限制：

- 不擅长长尾探索
- 当前 tool-call 资源主要覆盖 `knowledge_query` 和 `sandbox_exec` 这类关键静态调用，还没有覆盖更细粒度节点内操作

### deerflow-sidecar

优点：

- 运行边界更清晰
- 更接近生产部署形态
- 与主进程依赖隔离更好

限制：

- tool-call 资源依赖 runtime 是否吐出足够字段
- execution stream 由 lite-interpreter 控制面 journal 投影，不是直接 attach 到原生 backend transport

### deerflow-embedded

优点：

- 调用链更短
- 调试时更方便

限制：

- 更依赖本地 Python 环境
- 与主进程耦合更紧
- execution stream 依然由 lite-interpreter 控制面投影

### sandbox

优点：

- 是最终代码执行 owner
- 有 AST 审计、session、artifact、execution record

限制：

- 不负责研究与规划
- 不负责动态 sub-agent

## 4. 推荐默认模式

当前推荐：

- 动态 runtime：`deerflow-sidecar`
- 最终执行：`sandbox`

原因：

- sidecar 更符合受控 runtime 设计
- sandbox 继续保留最终执行 owner 地位

## 5. 与 API 的关系

当前这些能力可以通过 API 查询：

- `GET /api/runtimes`
- `GET /api/runtimes/{runtime_id}/capabilities`
- `GET /api/conformance`
- `GET /api/diagnostics`

执行级资源可以通过：

- `GET /api/tasks/{task_id}/executions`
- `GET /api/executions/{execution_id}`
- `GET /api/executions/{execution_id}/artifacts`
- `GET /api/executions/{execution_id}/tool-calls`
- `GET /api/executions/{execution_id}/events`

## 6. 后续要补的能力

下一阶段最值得补的是：

- 更完整的 tool-call tracing
- static-chain 内部工具调用的正式资源化
- runtime support matrix 的自动生成，而不是文档手工维护
