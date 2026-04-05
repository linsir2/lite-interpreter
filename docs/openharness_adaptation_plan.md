# OpenHarness 吸收改造方案

## 1. 文档目的

这份文档的目标不是“把 lite-interpreter 改造成另一个 OpenHarness”，而是把 OpenHarness 里对我们真正有价值的设计思想吸收进来，用于增强：

- runtime 能力建模
- 流式执行事件建模
- artifact / tool-call / execution 资源表达
- diagnostics / conformance / support matrix

参考来源：

- Open Harness 官网：https://openharness.ai/
- GitHub README：https://github.com/jeffrschneider/OpenHarness
- Capability Manifest：https://github.com/jeffrschneider/OpenHarness/blob/main/spec/CAPABILITY_MANIFEST.md
- Harness Support Matrix：https://github.com/jeffrschneider/OpenHarness/blob/main/spec/HARNESS_SUPPORT_MATRIX.md
- MAPI 主规范：https://github.com/jeffrschneider/OpenHarness/blob/main/spec/openharness.mapi.md

## 2. 先说结论

OpenHarness 对 `lite-interpreter` 最有价值的不是现成业务实现，而是四个设计方向：

1. 用标准化 capability manifest 描述 runtime 的真实能力边界
2. 用统一 execution event 模型描述流式执行，而不是使用零散 payload
3. 把 artifact / tool-calls / diagnostics / conformance 变成正式资源
4. 用 support matrix 管理“不同 runtime / mode 到底支持什么”

而不该照搬的点是：

- 不要把 lite-interpreter 改成“完全 harness-agnostic 的壳”
- 不要削弱 DAG、blackboard、sandbox 和 harness governor 的 owner 地位
- 不要现在就为兼容性引入过重的全量 API 面

## 3. 概念映射

### 3.1 OpenHarness -> lite-interpreter

| OpenHarness 概念 | lite-interpreter 当前对应物 | 当前状态 |
| --- | --- | --- |
| Capability Manifest | `src/common/capability_registry.py` | 已有基础能力 registry，但缺少 domain/operation/limitation 视图 |
| Harness / Backend | `src/dynamic_engine/runtime_registry.py` + `runtime_backends.py` | 已有 backend seam，但没有标准 runtime profile 输出 |
| Execution | `task_id` + `dynamic_request` + `execution_record` | 已有 task/execution 信息，但 execution 还不是 API 一级资源 |
| Execution Stream | `event_bus` + `event_journal` + SSE | 已有事件流，但事件类型仍偏 ad-hoc |
| Tool Calls | 动态 trace / sandbox 调用 | 还没有正式 `tool-call` 资源 |
| Artifacts | `ExecutionRecord.artifacts` + `dynamic_artifacts` | 已有数据，但没有统一 artifacts API |
| Diagnostics | `GET /health` + logs + tests | 有基础设施，但没有 diagnostics 资源层 |
| Conformance | pytest 测试 | 有测试，但没有 “runtime 合规状态” 的系统化输出 |

### 3.2 我们已经有的基础

以下这些基础非常适合承接 OpenHarness 思想：

- `src/common/contracts.py`
- `src/common/capability_registry.py`
- `src/common/event_bus.py`
- `src/common/event_journal.py`
- `src/dynamic_engine/runtime_registry.py`
- `src/dynamic_engine/trace_normalizer.py`
- `src/mcp_gateway/tools/sandbox_exec_tool.py`
- `src/blackboard/schema.py`
- `src/api/routers/sse_router.py`

也就是说，我们不是从零开始，而是已经有“局部版本”的 OpenHarness-style seams。

## 4. 值得吸收的 5 条设计原则

### 原则 1：能力必须显式描述，不要隐含在实现里

现在我们只知道：

- `deerflow` 是 runtime backend
- `researcher` profile 允许哪些工具
- sandbox 能执行代码

但还不知道：

- runtime 到底支持哪些 domain
- 支持哪些 operation
- 有哪些 limitation
- sidecar 和 embedded 的差异是什么

OpenHarness 的启发是：

- 把能力差异显式化
- 让系统、前端、测试、运维都能读同一份能力清单

### 原则 2：流式事件需要有统一类型系统

我们现在的动态 trace 能工作，但事件更像“格式化后的 payload”，而不是正式事件模型。

OpenHarness 的启发是：

- 文本输出、思考、tool-call、artifact、progress、error、done 都应该有明确类型
- SSE 不应该只是“转发 dict”
- 事件模型应支持重放、筛选、前端渲染和 conformance 检查

### 原则 3：execution 是资源，不只是过程

现在我们更像是“task owner”系统，而不是“task + execution”双层系统。

这会带来一个问题：

- tool-calls、artifacts、logs、resume/attach 都只能挂在 task 上

OpenHarness 的启发是：

- execution 也应该被看作正式资源
- task 可以有 execution
- execution 可以有 artifacts / tool-calls / logs / stream

### 原则 4：诊断和合规必须系统化

我们已经有不少测试，但它们只存在于 pytest。

OpenHarness 的启发是：

- 某个 runtime 是否支持 stream/artifact/subagent/tool-call，不应该靠读代码推断
- 这些结果应该能被系统直接汇报

### 原则 5：support matrix 是架构资产

OpenHarness 的矩阵思路特别适合我们这种多执行模式系统：

- `deerflow-sidecar`
- `deerflow-embedded`
- `static-chain`
- `sandbox-only`

这些模式之间天然存在能力差异，不写清楚，后续很难扩展。

## 5. 不适合照搬的内容

### 5.1 不要削弱 DAG owner

OpenHarness 是统一 harness 抽象层项目。

而 `lite-interpreter` 的核心价值在于：

- DAG 是系统 owner
- blackboard 是系统事实源
- sandbox 是执行 owner
- harness governor 是风险 owner

不能为了抽象层整齐，把这些 owner 关系搞丢。

### 5.2 不要一次性引入完整 API 面

OpenHarness 把很多资源都做成 API：

- agents
- skills
- sessions
- memory
- subagents
- executions
- diagnostics
- conformance

这对我们是方向，不是一步到位目标。

当前更适合先落这些：

- runtimes
- runtime capabilities
- execution stream typing
- artifacts
- tool-calls
- diagnostics
- conformance summary

## 6. 建议落地方案

### 阶段 A：Runtime Capability Manifest

目标：

- 让 runtime 能力和边界显式化

新增或修改：

- `src/common/contracts.py`
- `src/common/capability_registry.py`
- `src/dynamic_engine/runtime_registry.py`
- `src/dynamic_engine/runtime_backends.py`
- `src/api/routers/analysis_router.py` 或新增 runtime router

建议新增模型：

- `CapabilityOperation`
- `CapabilityDomainManifest`
- `RuntimeCapabilityManifest`
- `RuntimeSupportProfile`

建议能力 domain：

- `planning`
- `research`
- `tool_calls`
- `sandbox_execution`
- `state_sync`
- `streaming`
- `artifacts`
- `subagents`
- `memory`
- `sessions`

建议 limitation 字段：

- `network_access`
- `max_steps`
- `supports_resume`
- `supports_attach_stream`
- `supports_tool_call_trace`
- `supports_artifact_listing`
- `requires_sidecar`
- `requires_python>=3.12`

建议 API：

- `GET /api/runtimes`
- `GET /api/runtimes/{runtime_id}/capabilities`

### 阶段 B：Execution Event V2

目标：

- 把动态 trace 和 sandbox 事件统一成正式事件模型

新增或修改：

- `src/common/contracts.py`
- `src/common/schema.py`
- `src/dynamic_engine/trace_normalizer.py`
- `src/common/event_bus.py`
- `src/api/routers/sse_router.py`
- `src/frontend/components/status_stream.py`

建议新增事件类型：

- `text`
- `thinking`
- `progress`
- `tool_call_start`
- `tool_call_delta`
- `tool_call_end`
- `tool_result`
- `artifact`
- `governance`
- `error`
- `done`

建议方式：

- 不直接替换现有事件结构
- 先在 trace payload 中引入语义化执行事件，最终统一收口为 `ExecutionEvent`
- 再逐步把前端和 SSE 输出迁移到新结构

### 阶段 C：Execution Resource Layer

目标：

- 把 execution 相关对象从 task 附属字段升级为正式资源

新增或修改：

- `src/common/contracts.py`
- `src/blackboard/schema.py`
- `src/sandbox/execution_reporting.py`
- `src/api/routers/analysis_router.py`
- 可新增 `src/api/routers/execution_router.py`

建议新增资源：

- `ExecutionSummary`
- `ToolCallRecord`
- `ArtifactIndexRecord`
- `ExecutionLogRef`

建议 API：

- `GET /api/tasks/{task_id}/executions`
- `GET /api/executions/{execution_id}`
- `GET /api/executions/{execution_id}/artifacts`
- `GET /api/executions/{execution_id}/tool-calls`

注意：

- 第一版 execution id 可以直接复用 `trace_id` / `session_id`
- 不必先引入复杂多 execution per task 模型

### 阶段 D：Diagnostics & Conformance

目标：

- 让系统可回答“这个 runtime 到底支持什么，当前状态如何”

新增或修改：

- `src/api/main.py`
- 新增 `src/api/routers/diagnostics_router.py`
- 新增 `src/api/routers/conformance_router.py`
- `tests/test_dynamic_runtime.py`
- `tests/test_api_sse.py`
- `tests/test_e2e.py`

建议 API：

- `GET /health`
  保留，继续作为最小健康检查
- `GET /api/diagnostics`
  返回外部依赖、环境、runtime 状态
- `GET /api/conformance`
  返回 runtime 支持矩阵和测试/合规状态摘要

建议 diagnostics 内容：

- 当前 conda env 是否为 `lite_interpreter`
- Python 版本
- DeerFlow runtime mode
- sidecar 可达性
- Docker 可达性
- Postgres / Qdrant / Neo4j 可达性

### 阶段 E：Support Matrix 文档化

目标：

- 建立我们自己的 runtime support matrix

建议新增：

- `docs/runtime_support_matrix.md`

建议矩阵比较对象：

- `static-chain`
- `deerflow-sidecar`
- `deerflow-embedded`
- `sandbox-only`

建议比较项：

- supports planning
- supports dynamic research
- supports sandbox execution
- supports streaming
- supports attach stream
- supports artifacts
- supports tool-call trace
- supports resume

## 7. 建议具体改哪些文件

### 第一优先级

- `src/common/contracts.py`
- `src/common/capability_registry.py`
- `src/dynamic_engine/runtime_registry.py`
- `src/dynamic_engine/trace_normalizer.py`
- `src/api/routers/sse_router.py`

### 第二优先级

- `src/blackboard/schema.py`
- `src/sandbox/execution_reporting.py`
- `src/api/routers/analysis_router.py`
- `src/frontend/components/status_stream.py`

### 第三优先级

- `docs/architecture.md`
- `docs/code_tour.md`
- `docs/project_plan.md`
- 新增 `docs/runtime_support_matrix.md`

## 8. 一个适合我们的最小落地版本

如果只做最小收益版本，我建议按这个顺序：

1. runtime capability manifest
2. trace event v2
3. diagnostics endpoint
4. conformance summary

原因：

- 这四步对现有系统侵入最小
- 对可解释性提升最大
- 不需要一次性重做 API 面

## 9. 成功标准

完成后，系统应该能够直接回答这些问题：

1. 当前 runtime 支持哪些能力？
2. sidecar 和 embedded 有什么差异？
3. 一个 execution 产生了哪些 artifact？
4. 一个 execution 调用了哪些工具？
5. 当前系统是否支持 resume / attach stream？
6. 当前环境是否满足运行条件？
7. 某个 runtime 在 support matrix 中处于什么级别？

## 10. 建议下一步

最建议先做：

1. `RuntimeCapabilityManifest`
2. `GET /api/runtimes`
3. `GET /api/runtimes/{runtime_id}/capabilities`
4. `ExecutionEvent`

这一步做完，`lite-interpreter` 就会从“有 runtime seam 的系统”升级成“对 runtime 能力和边界有明确自描述能力的系统”。
