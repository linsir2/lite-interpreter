# lite-interpreter 架构说明

`lite-interpreter` 的目标，不是让模型“看起来很聪明”，而是把一条真实的数据分析任务链路做成可治理、可观测、可回放、可交付的系统。

当前成熟度、测试基线与已知热点统一以 `docs/reference/project-status.md` 为准；本文件只解释系统结构、协作关系与边界设计。

## 1. 系统总览

系统现在由六个协作层组成：

1. **产品层**：`apps/web` 提供真实 Web 工作台
2. **产品 API 层**：`/api/app/*` 提供稳定的 app-facing 合同
3. **控制层**：Blackboard、Event Bus、Event Journal 持有状态事实源
4. **编排层**：DAG 静态链负责主流程 owner 身份
5. **动态运行层**：DeerFlow sidecar 负责受控研究，不负责最终执行
6. **执行与知识层**：Sandbox、KAG、SkillNet 负责执行、安全、知识与方法沉淀

对应关系可以粗略看成：

```text
Web frontend
  -> /api/app/*
  -> blackboard-backed read models
  -> DAG static chain / DeerFlow dynamic research
  -> sandbox execution + KAG + SkillNet
  -> artifacts / audit / memory / status projections
```

## 2. 端到端主链路

### 2.1 创建分析

1. 前端通过 `POST /api/app/analyses` 提交问题、工作区和 `assetIds`
2. `src/api/services/task_flow_service.py` 创建任务与执行上下文
3. Blackboard 建立任务主状态
4. DAG 根据任务内容决定走静态链还是动态链

### 2.2 任务执行

- **静态链**：适合结构稳定、可确定性执行的分析任务
- **静态单次取证**：适合“先查一个公开事实，再做本地计算”的任务，仍归静态链 owner
- **动态链**：只保留给需要多步规划、反复探索、子 agent 编排的任务
- 三条路径都必须回写 Blackboard，最终结果统一由 summarizer 收束

### 2.3 结果消费

前端不直接碰底层执行对象，而是只消费 server-built 读模型：

- 分析列表：`GET /api/app/analyses`
- 分析详情：`GET /api/app/analyses/{analysis_id}`
- 事件轮询：`GET /api/app/analyses/{analysis_id}/events`
- 产物内容：`GET /api/app/analyses/{analysis_id}/outputs/{output_id}`

## 3. 六个协作层

### 3.1 产品层：真实 Web 前端

核心文件：

- `apps/web/src/app/App.tsx`
- `apps/web/src/app/AppShell.tsx`
- `apps/web/src/lib/api.ts`
- `apps/web/src/pages/*`

职责：

- 管理会话、工作区切换与页面路由
- 渲染分析、资料、方法、审计四类主要读模型
- 通过 Bearer Token 调用 `/api/app/*`
- 通过 polling 获取分析事件，不再依赖浏览器 query token

重要边界：

- 前端不再直接消费 legacy task / execution 风格公开接口
- 前端不自己拼凑多份真相，优先读取 server-built payload
- 产物读取必须走内容 API，不直接暴露任意本地绝对路径

### 3.2 产品 API 层：app-facing 合同

核心文件：

- `src/api/main.py`
- `src/api/routers/app_router.py`
- `src/api/app_schemas.py`
- `src/api/app_presenters.py`
- `src/api/services/task_flow_service.py`
- `src/api/services/asset_service.py`

职责：

- 对前端暴露稳定、可理解的业务合同
- 把底层 blackboard / execution / asset / audit 数据投影为产品读模型
- 处理会话、工作区 scope、角色约束与审计打点

当前明确收口：

- 只保留 `/api/app/*` 作为产品前端主接口
- 旧产品面接口已从公开路由表移除
- 运行时诊断、策略与 capability 接口保留在 `/api/*`，但不属于主产品工作台合同

### 3.3 控制层：Blackboard 作为事实源

核心文件：

- `src/blackboard/global_blackboard.py`
- `src/blackboard/execution_blackboard.py`
- `src/blackboard/knowledge_blackboard.py`
- `src/blackboard/memory_blackboard.py`
- `src/common/contracts.py`
- `src/common/event_bus.py`
- `src/common/event_journal.py`

职责：

- 保存任务生命周期主状态
- 保存执行态、知识态与记忆态快照
- 发布实时事件与历史回放
- 为 app-facing API 提供统一读模型输入

架构原则：

- Blackboard 是事实源，不允许模块绕开它传隐式状态
- Event Bus 负责实时流，Event Journal 负责可回放性
- API 层读的是投影结果，不直接把底层内部对象暴露给前端

### 3.4 编排层：DAG 仍是 owner

核心文件：

- `src/dag_engine/dag_graph.py`
- `src/dag_engine/graphstate.py`
- `src/dag_engine/nodes/router_node.py`
- `src/dag_engine/nodes/analyst_node.py`
- `src/dag_engine/nodes/coder_node.py`
- `src/dag_engine/nodes/auditor_node.py`
- `src/dag_engine/nodes/executor_node.py`
- `src/dag_engine/nodes/summarizer_node.py`

核心原则：

1. 静态链优先
2. 外部取证不等于动态；单次取证优先留在静态链
3. 动态能力只在需要迭代探索时触发
3. 最终执行仍回到本地 sandbox
4. summarizer 必须反映真实终态，而不是假象

静态链：

```text
router
  -> data_inspector
  -> kag_retriever
  -> context_builder
  -> analyst
  -> (必要时 static_evidence)
  -> coder
  -> auditor
  -> executor
  -> skill_harvester
  -> summarizer
```

动态链：

```text
router
  -> dynamic_swarm
  -> (必要时回流 analyst/coder/executor)
  -> skill_harvester
  -> summarizer
```

### 3.5 动态运行层：DeerFlow sidecar only

核心文件：

- `src/dynamic_engine/supervisor.py`
- `src/dynamic_engine/deerflow_bridge.py`
- `src/dynamic_engine/runtime_backends.py`
- `src/dynamic_engine/trace_normalizer.py`
- `src/dag_engine/nodes/dynamic_swarm_node.py`

当前只支持：

- **DeerFlow sidecar**

已经明确废弃：

- embedded Python client 模式
- auto runtime mode

职责边界：

- 负责复杂研究、外部资料探索、轨迹标准化
- 不拥有最终 Python 执行边界
- 不能替代 DAG 的 owner 身份

### 3.6 执行与知识层

#### 执行层

核心文件：

- `src/sandbox/ast_auditor.py`
- `src/sandbox/docker_executor.py`
- `src/sandbox/execution_reporting.py`
- `src/mcp_gateway/tools/sandbox_exec_tool.py`

职责：

1. 输入校验
2. AST 审计
3. tool-mediated static evidence 与 sandbox execute 的分段 governance
4. Docker sandbox 执行
5. `ExecutionRecord` 标准化
6. 产物与执行事件投影
7. artifact contract verification

#### 知识与方法层

核心文件：

- `src/kag/*`
- `src/skillnet/*`
- `src/memory/memory_service.py`
- `src/storage/repository/knowledge_repo.py`
- `src/storage/repository/memory_repo.py`

职责：

- 解析业务文档、构建知识、召回证据
- 在成功路径中沉淀复用方法
- 保存使用结果与 outcome，用于后续推荐与提升

## 4. 前端与 API 的合同边界

### 4.1 会话与权限

- 前端必须通过 `Authorization: Bearer <token>` 调用 API
- 会话 bootstrap 只走 `GET /api/app/session`
- 工作区切换通过 `workspaceId` query 参数进入 app-facing 合同

### 4.2 资料与任务输入

- 工作区上传资料只会进入当前 workspace 资产池
- 创建分析时必须通过 `assetIds` 显式挂接输入
- 不再允许“一个 workspace 里的所有资料自动污染每个任务”

### 4.3 结果产物

- 产物元数据由分析详情返回
- 产物内容/下载必须走 `outputs/{output_id}` API
- 不再把任意绝对路径直接暴露给前端

## 5. 迁移后的明确结论

这次迁移完成了两个非常重要的收口：

1. **产品面从 Streamlit 硬切到真实 Web 前端**
2. **公开产品接口从旧 tasks/executions 风格硬切到 `/api/app/*`**

因此，后续任何改动都应该遵守下面的判断：

- 不要再恢复旧公开产品接口
- 不要再把实验性质的运行时模式包装成正式能力
- 不要让文档、配置与路由表再次出现两套真相

## 6. 现在最值得盯的风险

当前结构已经比以前清楚很多，但仍有几个需要持续警惕的点：

1. `src/sandbox/docker_executor.py` 体量仍然偏大
2. `static_codegen` 仍然偏模板化
3. Web 前端已经成型，但输出预览、长任务反馈等体验还可以继续增强
4. Skill usage/outcome 的跨进程并发一致性仍需继续补强
