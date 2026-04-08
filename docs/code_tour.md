# lite-interpreter 代码导读

这份文档的目标不是“让你把所有文件都翻一遍”，而是帮你快速建立三层认知：

1. 项目有哪些模块
2. 模块之间怎么协作
3. 遇到一个问题时应该先看哪里

## 1. 先读什么

第一次进入仓库，推荐顺序：

1. `README.md`
2. `directory.txt`
3. `docs/architecture.md`
4. `docs/runtime_support_matrix.md`
5. `config/settings.py`
6. `src/common/contracts.py`
7. `src/blackboard/schema.py`

这几步看完后，你会知道：

- 这个系统不是纯 agent，而是受控 runtime
- 哪些模块属于控制面、运行面、执行面、知识面
- 运行环境默认是 conda 的 `lite_interpreter`

## 2. 环境和入口

### 2.1 环境

默认环境：

- conda env: `lite_interpreter`

推荐检查：

```bash
conda run -n lite_interpreter python -V
conda run -n lite_interpreter python -c "import streamlit; import deerflow.client; print('ok')"
conda run -n lite_interpreter python scripts/smoke_dashscope_litellm.py
```

### 2.2 运行入口

看这几个文件：

1. `Makefile`
2. `config/settings.py`
3. `litellm_config.yml`
4. `config/harness_policy.yaml`

重点：

- `Makefile` 已默认走 `conda run -n lite_interpreter`
- DeerFlow 运行模式相关变量是否配置正确
- LiteLLM alias 是否对应到 DashScope
- harness profile / deny pattern 是否符合预期

## 3. 按模块阅读

### 3.1 控制面

先看：

1. `src/common/contracts.py`
2. `src/blackboard/schema.py`
3. `src/blackboard/global_blackboard.py`
4. `src/blackboard/execution_blackboard.py`
5. `src/blackboard/knowledge_blackboard.py`
6. `src/common/event_bus.py`
7. `src/common/event_journal.py`

你要回答的问题：

- 系统用什么结构表示任务、意图、决策、执行结果
- 哪些状态只在内存，哪些会持久化
- 执行态和知识态为什么要分成两个子黑板
- 事件如何被实时投递，如何被 backlog 回放

如果你在查：

- “任务为什么查不到”
- “SSE 为什么没收到事件”
- “为什么 final response 有了但状态不对”

就从这组文件开始。

### 3.2 路由与 DAG

先看：

1. `src/dag_engine/dag_graph.py`
2. `src/dag_engine/graphstate.py`
3. `src/dag_engine/nodes/router_node.py`

重点：

- Router 何时走静态链，何时走动态链
- `ExecutionIntent` 如何写回黑板
- LangGraph 中的 conditional edges 是怎么定义的

如果你在查：

- “这个 query 为什么走 dynamic”
- “为什么没进 KAG”
- “为什么静态链直接跳 Analyst”

就从 Router 开始。

### 3.3 静态链

顺序：

1. `src/dag_engine/nodes/data_inspector.py`
2. `src/dag_engine/nodes/kag_retriever.py`
3. `src/dag_engine/nodes/context_builder_node.py`
4. `src/dag_engine/nodes/analyst_node.py`
5. `src/dag_engine/nodes/coder_node.py`
6. `src/dag_engine/nodes/static_codegen.py`
7. `src/dag_engine/nodes/auditor_node.py`
8. `src/dag_engine/nodes/executor_node.py`
9. `src/dag_engine/nodes/skill_harvester_node.py`
10. `src/dag_engine/nodes/summarizer_node.py`

重点：

- `data_inspector` 负责结构化文件 schema/load_kwargs
- `kag_retriever` 负责文档入库和知识检索
- `context_builder` 负责把检索结果压缩成 business context
- `analyst` 负责最小计划
- `coder` 负责静态代码 payload 装配和 codegen
- `static_codegen` 是 coder 的 helper，不是 DAG 节点
- `auditor` 决定走 executor 还是 debugger
- `executor` 只负责执行与写 execution record
- `summarizer` 统一输出 final response

如果你在查：

- “为什么生成代码里有某条技能提示”
- “为什么规则/指标/过滤条件是这样进代码的”
- “为什么状态停在 summarizing”

重点看 `coder_node.py`、`static_codegen.py`、`executor_node.py`、`analysis_router.py`。

### 3.4 动态链

顺序：

1. `src/dynamic_engine/blackboard_context.py`
2. `src/dynamic_engine/supervisor.py`
3. `src/dynamic_engine/runtime_registry.py`
4. `src/dynamic_engine/runtime_gateway.py`
5. `src/dynamic_engine/runtime_backends.py`
6. `src/dynamic_engine/deerflow_bridge.py`
7. `src/dynamic_engine/trace_normalizer.py`
8. `src/dag_engine/nodes/dynamic_swarm_node.py`

重点：

- 动态节点不是系统 owner，DAG 才是
- `DynamicSupervisor` 会先做治理决策
- deny 不会进 runtime
- sidecar / embedded / auto 三种模式都在 `DeerflowBridge`
- dynamic trace 会经过 normalizer 再写入 blackboard 和 SSE

如果你在查：

- “为什么动态请求被拒绝”
- “为什么 sidecar 没跑起来”
- “为什么 trace 在前端显示不对”

就从 `dynamic_swarm_node.py` 和 `deerflow_bridge.py` 开始。

### 3.5 执行面

顺序：

1. `src/sandbox/ast_auditor.py`
2. `src/sandbox/session_manager.py`
3. `src/sandbox/execution_reporting.py`
4. `src/sandbox/docker_executor.py`
5. `src/mcp_gateway/tools/sandbox_exec_tool.py`

重点：

- 先审计，再执行
- session 如何创建、运行、完成
- governance/status/artifact 事件如何投射
- `ExecutionRecord` 如何标准化输出

如果你在查：

- “为什么 sandbox deny 没被前端看到”
- “为什么 execution_record 结构不一致”
- “为什么 task 级 sandbox 事件没发”

先看 `execution_reporting.py` 和 `sandbox_exec_tool.py`。

### 3.6 知识面

顺序：

1. `src/kag/builder/parser.py`
2. `src/kag/builder/classifier.py`
3. `src/kag/builder/orchestrator.py`
4. `src/kag/builder/embedding.py`
5. `src/kag/retriever/query_engine.py`
6. `src/kag/context/*`
7. `src/storage/repository/knowledge_repo.py`

重点：

- 文档如何从解析进入 chunk/vector/graph
- QueryEngine 怎样返回 `EvidencePacket`
- ContextBuilder 怎样用 budget 控制上下文大小

如果你在查：

- “为什么 business_context 为空”
- “为什么检索结果没有 evidence refs”
- “为什么 parser report 没写到最终结果”

看 `kag_retriever.py`、`query_engine.py`、`context_builder_node.py`。

### 3.7 SkillNet

顺序：

1. `src/skillnet/skill_schema.py`
2. `src/skillnet/dynamic_skill_adapter.py`
3. `src/skillnet/skill_validator.py`
4. `src/skillnet/skill_promoter.py`
5. `src/skillnet/skill_retriever.py`
6. `src/storage/repository/memory_repo.py`

重点：

- 技能从哪里来
- 需要什么 capability
- 什么情况下变成 approved
- 历史技能怎么回流到 router/analyst/coder

如果你在查：

- “为什么这个技能没被复用”
- “为什么 historical skill match 有但没参与 codegen”
- “为什么 usage telemetry 没更新”

就从 `skill_retriever.py` 和 `memory_repo.py` 开始。

### 3.8 API 与前端

API 顺序：

1. `src/api/main.py`
2. `src/api/routers/analysis_router.py`
3. `src/api/routers/execution_router.py`
4. `src/api/routers/sse_router.py`
5. `src/api/schemas.py`

前端顺序：

1. `src/frontend/app.py`
2. `src/frontend/pages/task_console.py`
3. `src/frontend/components/status_stream.py`

重点：

- 创建任务后 `autorun` 怎么启动后台链路
- `/result` 返回哪些控制面字段
- `/executions` / `/artifacts` / `/tool-calls` / `/events` 怎么从 blackboard + journal 派生
- SSE 如何先发 backlog 再接实时流
- 前端如何显示 status/governance/trace
- `task_console` 何时优先 attach execution stream，何时退回 task stream
- 静态链如何通过 synthetic `knowledge_query` / `sandbox_exec` 补齐 tool-call 资源

## 4. 看什么测试

建议按模块对应测试看：

- `tests/test_blackboard.py`
- `tests/test_api_sse.py`
- `tests/test_dag_engine.py`
- `tests/test_dynamic_runtime.py`
- `tests/test_harness.py`
- `tests/test_sandbox.py`
- `tests/test_skillnet.py`
- `tests/test_kag.py`
- `tests/test_e2e.py`

如果你只想快速确认主链：

```bash
conda run -n lite_interpreter python -m pytest -q \
  tests/test_blackboard.py \
  tests/test_api_sse.py \
  tests/test_dag_engine.py \
  tests/test_dynamic_runtime.py \
  tests/test_e2e.py
```

## 5. 最快定位问题的方法

### 状态问题

看：

- `global_blackboard.py`
- `execution_blackboard.py`
- `analysis_router.py`

### 动态链问题

看：

- `router_node.py`
- `dynamic_swarm_node.py`
- `deerflow_bridge.py`

### sandbox 问题

看：

- `ast_auditor.py`
- `docker_executor.py`
- `execution_reporting.py`

### 检索问题

看：

- `kag_retriever.py`
- `query_engine.py`
- `context_builder_node.py`

### 技能复用问题

看：

- `skill_retriever.py`
- `memory_repo.py`
- `coder_node.py`

## 6. 推荐的阅读方式

不要按目录“从上到下全看完”，而是按一条链路走：

1. 任务从 API 进入
2. Router 做决策
3. 进入静态链或动态链
4. 写回 blackboard
5. 通过 event bus / SSE 投给前端
6. summarizer 产出 final response

这样更快，也更接近真实排障路径。
