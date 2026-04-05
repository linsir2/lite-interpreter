# lite-interpreter 架构说明

## 1. 总体目标

`lite-interpreter` 不是一个“让 agent 自由发挥”的系统，而是一个把任务执行、治理、知识检索、动态探索都纳入控制面的数据智能运行时。

核心目标：

- 让稳定流程走确定性 DAG
- 让复杂长尾问题走受控动态节点
- 让代码执行始终留在本地 sandbox
- 让治理决策、状态变化、轨迹和结果都能回放与审计

## 2. 四层架构

### 2.1 控制面

控制面负责“知道系统当前在干什么”。

关键模块：

- `src/blackboard/global_blackboard.py`
- `src/blackboard/execution_blackboard.py`
- `src/blackboard/knowledge_blackboard.py`
- `src/common/contracts.py`
- `src/common/event_bus.py`
- `src/common/event_journal.py`

核心对象：

- `TaskEnvelope`
  任务信封，包含 task/tenant/workspace/query/governance/budget
- `ExecutionIntent`
  Router 的执行决策，决定 static/dynamic/hybrid
- `DecisionRecord`
  Harness 的治理决策记录
- `TraceEvent`
  统一事件结构，用于 SSE 和重放
- `ExecutionEvent`
 统一流式执行事件结构，补充 `text / thinking / progress / artifact / tool-call / done` 语义层
- `ExecutionRecord`
  Sandbox/Runtime 的标准化执行记录
- `RuntimeCapabilityManifest`
  runtime 的能力自描述，用于 capability inspection / conformance / support matrix
- `ToolCallRecord`
  从 execution trace 派生出的正式 tool-call 资源

控制面职责：

- 保存任务状态
- 保存执行状态
- 投递事件
- 提供重放 backlog
- 让 API 和前端能看到统一的任务视图
- 提供 runtime capability / diagnostics / conformance / execution resource 查询

### 2.2 运行面

运行面负责“任务如何被编排”。

关键模块：

- `src/dag_engine/dag_graph.py`
- `src/dag_engine/nodes/router_node.py`
- `src/dag_engine/nodes/dynamic_swarm_node.py`
- `src/dynamic_engine/supervisor.py`
- `src/dynamic_engine/runtime_gateway.py`
- `src/dynamic_engine/runtime_registry.py`
- `src/dynamic_engine/deerflow_bridge.py`

设计要点：

- DAG 是 owner
- Router 先决定静态链还是动态链
- 动态链是一个超级节点，不是满系统散落的 agent
- DeerFlow 是 runtime backend，不是系统 owner

当前动态链分层：

1. `DynamicSupervisor`
   生成 `DynamicRunPlan`，封装 task envelope、execution intent、governance decision
2. `RuntimeGateway`
   根据 registry 选择 runtime backend
3. `DeerflowBridge`
   执行 embedded / sidecar / auto 模式
4. `TraceNormalizer`
   把 runtime 事件统一成系统可消费的 trace

运行面新增的能力自描述接口：

- `runtime_registry` 不再只负责 `create(backend)`，现在也能输出 runtime capability manifest
- API 已可通过 `/api/runtimes` 和 `/api/runtimes/{id}/capabilities` 查询 runtime 支持情况

### 2.3 执行面

执行面负责“代码怎样被安全执行”。

关键模块：

- `src/sandbox/ast_auditor.py`
- `src/sandbox/docker_executor.py`
- `src/sandbox/session_manager.py`
- `src/sandbox/execution_reporting.py`
- `src/mcp_gateway/tools/sandbox_exec_tool.py`

执行面流程：

1. 代码输入校验
2. AST 安全审计
3. Harness sandbox policy 判断
4. Docker 容器执行
5. 生成 `SandboxResult`
6. 标准化成 `ExecutionRecord`
7. 写回黑板并向前端投递事件
8. 通过 execution resource layer 暴露 execution / artifacts / tool-calls

当前关键边界：

- 代码执行只发生在本地 sandbox
- 动态链可以探索，但不能绕过本地 sandbox 执行代码
- 输入挂载显式、只读
- artifact 有明确输出目录
- tool-call 资源从 trace 派生，不另起第二套执行状态存储

### 2.4 知识面

知识面负责“系统知道什么，以及怎么检索”。

关键模块：

- `src/kag/builder/*`
- `src/kag/retriever/*`
- `src/kag/context/*`
- `src/mcp_gateway/tools/knowledge_query_tool.py`
- `src/skillnet/*`

知识面包含两种资产：

1. 文档与图谱资产
   由 KAG builder 解析、分块、向量化、图谱抽取、入库
2. 技能资产
   由 SkillNet 从动态/静态成功路径中抽取、验证、提升并复用

KAG 设计原则：

- 保留 layout-aware / parent-child / fallback chunking
- 保留 hybrid recall
- 保留 graph recall
- 不把 KAG 简化成普通 hit list

SkillNet 设计原则：

- 候选技能必须带 `required_capabilities`
- 必须经过 validation 与 authorization
- 历史技能复用要能解释来源、原因、得分
- 任务完成后要把 success/failure 回写到 usage telemetry

## 2.5 观测与资源层

除了四层主架构，当前系统已经新增了一层“资源化观测面”，用于把已有 blackboard 状态转成正式资源：

- runtime capability manifest
- diagnostics
- conformance
- executions
- artifacts
- tool-calls
- execution streams

关键模块：

- `src/api/routers/runtime_router.py`
- `src/api/routers/diagnostics_router.py`
- `src/api/routers/execution_router.py`
- `src/api/execution_resources.py`
- `src/api/diagnostics_resources.py`

这层的设计原则是：

- 不另起新的状态源
- 直接从 blackboard / state repo / runtime registry 派生
- 先提供稳定只读资源，再决定是否演进成独立生命周期对象

## 3. 主链路

### 3.1 静态链

静态链适合 SOP、已有业务知识、已上传数据、低复杂度任务。

链路如下：

1. `router_node`
2. `data_inspector`（如有结构化数据且未探查）
3. `kag_retriever`（如需企业知识）
4. `context_builder`
5. `analyst_node`
6. `coder_node`
7. `auditor_node`
8. `executor_node`
9. `skill_harvester_node`
10. `summarizer_node`

### 3.2 动态链

动态链适合复杂、未知、多步、需要探索和验证闭环的任务。

链路如下：

1. `router_node`
2. `dynamic_swarm_node`
3. `skill_harvester_node`
4. `summarizer_node`

## 4. 模块协作关系

### 4.1 Router 与 Blackboard

- Router 从 `ExecutionBlackboard` 读取上下文
- Router 把 `routing_mode / complexity_score / candidate_skills / execution_intent` 写回
- 后续节点不需要重复推断执行意图

### 4.2 Dynamic Runtime 与 Harness

- `DynamicSupervisor` 在 runtime 执行前调用 `HarnessGovernor`
- deny 会直接生成 denied patch，不继续执行 DeerFlow
- allow 才进入 runtime gateway

### 4.3 Sandbox 与 Harness

- `docker_executor` 在容器启动前做 governance 判断
- deny 结果也会像正常执行结果一样落 session、落事件、落 blackboard

### 4.4 SSE 与 Event Journal

- `event_bus` 负责实时投递
- `event_journal` 负责 backlog 保存
- `sse_router` 先发 connected，再回放 backlog，再继续实时订阅
- `TraceNormalizer` 已把 runtime trace 统一收口成 canonical `ExecutionEvent`

### 4.5 Execution Resource Layer

- `ExecutionData` 仍然是唯一事实来源
- `execution_resources.py` 从 `ExecutionData` 派生：
  - execution summary
  - artifact list
  - tool-call list
  - execution stream
- `event_journal` + `execution_resources.py` 共同派生 execution stream
- static-chain 当前也会派生 synthetic tool calls：
  - `knowledge_query`
  - `sandbox_exec`
- 前端 `task_console` 已开始主动调用：
  - `/api/tasks/{task_id}/executions`
  - `/api/executions/{execution_id}/tool-calls`
  - `/api/executions/{execution_id}/events`

## 5. 当前架构收益

- 宏观编排和微观探索分层明确
- Sandbox 边界清晰
- Harness 已真正进入关键路径
- 控制面契约统一
- SkillNet 不再只是“存描述”，而是开始具备复用闭环
- runtime 能力边界开始可自描述
- execution / artifacts / tool-calls 已成为正式 API 资源
- diagnostics / conformance 已有最小实现
- execution attach/resume stream 已有最小实现
- 前端已能区分 execution stream 与 task stream，并展示静态/动态 tool-call 资源

## 6. 当前架构风险

- `docker_executor.py` 仍然偏大
- 静态链后半段仍然是串行同步执行，后续可继续做更细粒度收敛
- 真实外部依赖环境下的 e2e 还不够多
- 目前更适合“受控原型/架构演示”，离生产级仍有工程化距离

## 7. 读代码建议

建议顺序：

1. `README.md`
2. `directory.txt`
3. `docs/code_tour.md`
4. `src/common/contracts.py`
5. `src/blackboard/schema.py`
6. `src/dag_engine/nodes/router_node.py`
7. `src/dynamic_engine/*`
8. `src/sandbox/*`
9. `src/kag/*`
10. `src/api/*`
