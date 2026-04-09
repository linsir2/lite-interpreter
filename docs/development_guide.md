# lite-interpreter 开发手册

## 1. 开发环境

默认开发环境：

- conda env: `lite_interpreter`

建议：

- 直接执行命令时用 `conda run -n lite_interpreter ...`
- 长时间本地调试时可先 `conda activate lite_interpreter`
- 阅读当前成熟度、测试基线与非目标时，优先看 `docs/project_status.md`

## 2. 开发原则

这个项目的核心原则不是“尽快把 agent 跑起来”，而是：

- 让控制面保持可解释
- 让执行边界保持可控
- 让状态变化可追踪
- 让动态 runtime 服从 DAG，而不是反过来

具体开发时要优先遵守：

- 保持 `TaskEnvelope / ExecutionIntent / DecisionRecord / ExecutionRecord` 的一致性
- 不绕开 blackboard 直接在节点之间传隐藏状态
- 不绕开 harness 直接做动态执行或 sandbox 执行
- 不把 DeerFlow 当系统 owner

## 3. 改动时先看哪里

### 改控制面

看：

- `src/common/contracts.py`
- `src/blackboard/schema.py`
- `src/blackboard/global_blackboard.py`
- `src/common/event_bus.py`

### 改静态链

看：

- `src/dag_engine/nodes/analyst_node.py`
- `src/dag_engine/nodes/coder_node.py`
- `src/dag_engine/nodes/static_codegen.py`
- `src/dag_engine/nodes/executor_node.py`
- `src/dag_engine/nodes/summarizer_node.py`

### 改动态链

看：

- `src/dynamic_engine/supervisor.py`
- `src/dynamic_engine/runtime_gateway.py`
- `src/dynamic_engine/deerflow_bridge.py`
- `src/dag_engine/nodes/dynamic_swarm_node.py`

### 改执行面

看：

- `src/sandbox/ast_auditor.py`
- `src/sandbox/docker_executor.py`
- `src/sandbox/execution_reporting.py`
- `src/mcp_gateway/tools/sandbox_exec_tool.py`

### 改知识面

看：

- `src/kag/builder/*`
- `src/kag/retriever/*`
- `src/kag/context/*`
- `src/storage/repository/knowledge_repo.py`

## 4. 推荐开发流程

### 4.1 改动前

1. 读 `directory.txt`
2. 读对应模块的现有实现
3. 先找已有测试
4. 明确你的改动属于：
   - 控制面
   - 运行面
   - 执行面
   - 知识面

### 4.2 改动中

- 优先抽 helper，不要让节点文件无限膨胀
- 尽量保留 DAG 节点只负责“节点编排”
- 通用逻辑往 helper / tool / repository / common 合并
- 外部接口不变时，优先做保守重构

### 4.3 改动后

至少执行：

```bash
conda run -n lite_interpreter python -m pytest -q
```

如果只是局部改动，也至少执行对应模块测试。

## 5. 测试策略

### 5.1 基础层

- `tests/test_blackboard.py`
- `tests/test_harness.py`
- `tests/test_llm_client.py`
- `tests/test_sandbox.py`

### 5.2 编排层

- `tests/test_dag_engine.py`
- `tests/test_dynamic_runtime.py`
- `tests/test_api_sse.py`

### 5.3 验收层

- `tests/test_e2e.py`

## 6. 常见改动建议

### 新增一个静态链能力

优先看：

- `router_node.py`
- `analyst_node.py`
- `coder_node.py`
- `static_codegen.py`
- `summarizer_node.py`

### 新增一个动态 runtime

优先看：

- `runtime_backends.py`
- `runtime_registry.py`
- `runtime_gateway.py`
- `dynamic_swarm_node.py`

### 新增一个可治理能力

优先看：

- `common/capability_registry.py`
- `harness/policy.py`
- `harness/governor.py`
- `skill_auth_tool.py`

### 新增一个知识检索通道

优先看：

- `kag/retriever/query_engine.py`
- `kag/retriever/recall/*`
- `knowledge_query_tool.py`

## 7. 当前技术债提醒

- `docker_executor.py` 仍然偏大
- 静态链节点仍然偏同步
- 前端更多是 demo 控制台，不是完整产品 UI
- 真正依赖 Docker/外部服务的环境 e2e 还可以继续增强

## 8. 文档同步要求

如果你改了这些内容，最好同步更新文档：

- 目录结构变动：更新 `directory.txt`
- 阅读顺序变动：更新 `docs/code_tour.md`
- 架构边界变动：更新 `docs/architecture.md`
- 启动命令变动：更新 `README.md` 与 `docs/deployment.md`
- 项目阶段变化：更新 `docs/project_plan.md`
- 当前测试基线或成熟度判断变化：更新 `docs/project_status.md`

这一步非常重要，不然下一次阅读代码的人会被旧文档误导。
