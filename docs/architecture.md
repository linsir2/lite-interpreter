# lite-interpreter 架构说明

## 1. 总体目标

`lite-interpreter` 的目标，是把一个真实的数据分析任务拆成可治理、可观测、可回放的工程闭环，而不是把所有事情都塞进一个 prompt。

当前成熟度、测试基线与已知热点统一以 `docs/project_status.md` 为准，这份文档只描述结构与边界。

系统当前最关键的设计原则有四条：

1. **DAG 仍是 owner**
   静态主链负责可预测、可审计、可回放的主流程。

2. **动态能力按需触发**
   只有在复杂、长尾、需要外部研究的任务上，才进入 DeerFlow sidecar。

3. **最终代码执行留在本地 sandbox**
   不把最终执行权交给动态 runtime。

4. **Blackboard 是事实源**
   所有任务状态、执行状态、知识状态和记忆状态都要回到控制面，不允许侧写隐状态。

## 2. 五个主面

### 2.1 控制面

核心模块：

- `src/blackboard/global_blackboard.py`
- `src/blackboard/execution_blackboard.py`
- `src/blackboard/knowledge_blackboard.py`
- `src/blackboard/memory_blackboard.py`
- `src/common/contracts.py`
- `src/common/event_bus.py`
- `src/common/event_journal.py`

核心职责：

- 维护任务生命周期状态
- 维护执行态主状态
- 维护知识态与记忆态快照
- 发布实时事件
- 提供 backlog 回放
- 支撑 API 读模型与前端工作台

关键共享对象：

- `TaskEnvelope`
- `ExecutionIntent`
- `DecisionRecord`
- `ExecutionRecord`
- `TraceEvent`
- `ToolCallRecord`
- `RuntimeCapabilityManifest`

### 2.2 路由与编排面

核心模块：

- `src/dag_engine/dag_graph.py`
- `src/dag_engine/graphstate.py`
- `src/dag_engine/nodes/router_node.py`
- `src/dag_engine/nodes/analyst_node.py`
- `src/dag_engine/nodes/coder_node.py`
- `src/dag_engine/nodes/auditor_node.py`
- `src/dag_engine/nodes/executor_node.py`
- `src/dag_engine/nodes/summarizer_node.py`

当前主判断：

- **静态链优先**
- **动态链按需触发**
- **动态研究后可回流静态链**
- **最终摘要必须反映真实终态**

当前主链顺序：

1. Router
2. 静态链或动态链
3. Skill Harvester
4. Summarizer
5. Analysis Workspace / execution resources

### 2.3 动态运行面

核心模块：

- `src/dynamic_engine/supervisor.py`
- `src/dynamic_engine/deerflow_bridge.py`
- `src/dynamic_engine/runtime_backends.py`
- `src/dynamic_engine/trace_normalizer.py`
- `src/dag_engine/nodes/dynamic_swarm_node.py`

当前只支持：

- **DeerFlow sidecar**

不再支持：

- embedded Python client 模式
- auto runtime mode

动态链职责边界：

- 处理复杂研究任务
- 发起受控外部检索/工具调用
- 产出研究摘要、trace、artifact refs、候选静态 skill
- 不直接拥有最终 Python 执行边界

### 2.4 执行面

核心模块：

- `src/sandbox/ast_auditor.py`
- `src/sandbox/docker_executor.py`
- `src/sandbox/session_manager.py`
- `src/sandbox/execution_reporting.py`
- `src/mcp_gateway/tools/sandbox_exec_tool.py`

当前执行流程：

1. 输入校验
2. AST 审计
3. harness governance 预判
4. Docker sandbox 执行
5. `ExecutionRecord` 标准化
6. task/execution 事件投影

当前安全边界：

- `tenant_id/workspace_id` 不再允许任意字符进入路径与 DB 标识符
- artifact path 只允许受控根目录或显式 URL
- session secret 不再允许默认固定值
- API 不再支持 query-string token

### 2.5 知识与技能面

核心模块：

- `src/kag/builder/*`
- `src/kag/retriever/*`
- `src/kag/context/*`
- `src/skillnet/*`
- `src/memory/memory_service.py`
- `src/storage/repository/knowledge_repo.py`
- `src/storage/repository/memory_repo.py`

KAG 当前职责：

- 文档解析
- chunk / embedding / graph
- 证据召回
- context 构建

SkillNet 当前职责：

- 动态或静态成功路径的 skill harvest
- validation / authorization / promotion
- 历史 skill recall 与 usage/outcome 回写

当前真实约束：

- 结构化静态执行可靠格式限定为 `csv/tsv/json`
- business document 与 structured dataset 不能再随意互相伪装
- durable memory 不可用时主链降级继续，不再直接卡死 router

## 3. 两条主链

### 3.1 静态链

```text
router
  -> data_inspector
  -> kag_retriever
  -> context_builder
  -> analyst
  -> coder
  -> auditor
  -> executor
  -> skill_harvester
  -> summarizer
```

适用场景：

- 结构比较稳定的分析任务
- 已知 SOP 或可模板化执行的问题
- 不需要大量外部研究与多步探索的问题

### 3.2 动态链

```text
router
  -> dynamic_swarm
  -> (必要时回流 analyst/coder/executor)
  -> skill_harvester
  -> summarizer
```

适用场景：

- 需要自己找资料
- 需要跨多步探索
- 需要动态研究后再收束成静态验证的问题

## 4. 前端和 API 的关系

前端不再自己拼多份真相，而是优先读取 server-built workspace payload。

关键接口：

- `GET /api/tasks/{task_id}/workspace`
- `GET /api/tasks/{task_id}/result`
- `GET /api/tasks/{task_id}/executions`
- `GET /api/tasks/{task_id}/events/poll`
- `GET /api/executions/{execution_id}`
- `GET /api/executions/{execution_id}/events/poll`
- `GET /api/executions/{execution_id}/artifacts`
- `GET /api/executions/{execution_id}/tool-calls`

当前前端主面：

- `Analysis Workspace`
- `Knowledge Assets`
- `Skill Library`
- `Audit Logs`

其中真正的主产品面仍是 `Analysis Workspace`。

### 4.1 产物消费边界

当前 artifact 消费分两层：

1. `execution_artifacts`
   - 列出 artifact 元数据
   - 包含稳定 `artifact_id`
   - 不再把任意绝对路径当作前端直接可读文件

2. `execution artifact content API`
   - 通过 `GET /api/executions/{execution_id}/artifacts/{artifact_id}` 读取受控内容
   - 只允许受控上传根和输出根内的本地文件
   - 文本/图片预览与下载都应走这条 API

### 4.2 workspace 资产到 task 输入

当前控制面已经把“workspace 资产”和“task 输入”拆开：

- workspace 上传只是把资产放进当前 workspace
- task 真正执行什么输入，必须通过 `workspace_asset_refs` 显式绑定
- 这样可以避免“一个 workspace 里所有资产自动污染每个新任务”的隐式行为

## 5. 当前最重要的工程结论

1. **系统核心不是“更多模块”，而是边界更清楚**
2. **动态能力不是越多越好，而是越可控越好**
3. **文档、测试、运行时 contract 必须保持一致**
4. **假支持比不支持更危险**
5. **所有最终用户可见结果，必须反映真实终态，而不是漂亮的假象**
