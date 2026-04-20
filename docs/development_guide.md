# lite-interpreter 开发手册

## 1. 开发环境

默认环境：

- conda env：`lite_interpreter`
- Python：`3.12`

推荐习惯：

- 单条命令执行时优先：`conda run -n lite_interpreter ...`
- 长时间交互调试时可先：`conda activate lite_interpreter`
- 任何改动前先读：`docs/project_status.md`

## 2. 开发原则

这个项目最重要的不是“把功能拼出来”，而是保持控制面、执行面、知识面和动态运行面的边界清楚。

开发时默认遵守：

1. 不绕开 Blackboard 传隐藏状态
2. 不绕开 Harness 直接做动态执行或 sandbox 执行
3. 不把 DeerFlow 当系统 owner
4. 不为了“看起来灵活”引入假支持
5. 改 bug 先补回归测试，再改实现

## 3. 常用命令

### 3.1 检查

```bash
conda run -n lite_interpreter python -m ruff check src tests scripts config
```

### 3.2 全量测试

```bash
conda run -n lite_interpreter python -m pytest -q
```

### 3.3 快速验收脚本

```bash
python3 scripts/check_hybrid_readiness.py
conda run -n lite_interpreter python scripts/smoke_dashscope_litellm.py
```

### 3.4 常用运行入口

```bash
make run-api
make run-sidecar
make run-frontend
make test-stream
```

## 4. 改动前先看哪里

### 控制面问题

先看：

- `src/common/contracts.py`
- `src/blackboard/schema.py`
- `src/blackboard/global_blackboard.py`
- `src/blackboard/execution_blackboard.py`
- `src/common/event_journal.py`
- `src/storage/repository/state_repo.py`

适用问题：

- 为什么任务状态不一致
- 为什么冷恢复失败
- 为什么 SSE 重放不对
- 为什么 execution 资源查不到

### 静态链问题

先看：

- `src/dag_engine/nodes/data_inspector.py`
- `src/dag_engine/nodes/kag_retriever.py`
- `src/dag_engine/nodes/context_builder_node.py`
- `src/dag_engine/nodes/analyst_node.py`
- `src/dag_engine/nodes/coder_node.py`
- `src/dag_engine/nodes/static_codegen.py`
- `src/dag_engine/nodes/auditor_node.py`
- `src/dag_engine/nodes/executor_node.py`
- `src/dag_engine/nodes/summarizer_node.py`

### 动态链问题

先看：

- `src/dynamic_engine/supervisor.py`
- `src/dynamic_engine/deerflow_bridge.py`
- `src/dynamic_engine/runtime_backends.py`
- `src/dag_engine/nodes/dynamic_swarm_node.py`

### 知识/技能问题

先看：

- `src/kag/builder/*`
- `src/kag/retriever/*`
- `src/skillnet/*`
- `src/memory/memory_service.py`
- `src/storage/repository/knowledge_repo.py`
- `src/storage/repository/memory_repo.py`

### API / 前端问题

先看：

- `src/api/main.py`
- `src/api/auth.py`
- `src/api/request_scope.py`
- `src/api/execution_resources.py`
- `src/api/routers/*`
- `src/frontend/components/status_stream.py`
- `src/frontend/pages/task_console.py`

## 5. 推荐改动流程

### 5.1 改动前

1. 找到对应模块与现有测试
2. 明确这是安全问题、一致性问题、产品流问题还是文档漂移问题
3. 能补回归测试的先补测试

### 5.2 改动中

- 优先做局部 helper 拆分，不做大重构
- 节点保持“编排职责”，复杂拼装逻辑尽量往 helper / service / repository 放
- 涉及最终用户结果的逻辑，优先保证“不要说错”

### 5.3 改动后

至少执行：

```bash
conda run -n lite_interpreter python -m ruff check src tests scripts config
conda run -n lite_interpreter python -m pytest -q
```

如果只改局部，也要至少跑对应测试文件。

## 6. 当前最值得小心的点

1. `src/sandbox/docker_executor.py` 仍然偏大
2. `static_codegen.py` 仍然偏模板化
3. 前端主工作台已经收口，但 artifact 消费仍需继续 API 化
4. KAG 的真实支持边界要保持诚实，不要再把没闭环的格式宣传成“支持”
5. docs 与 tests 的 contract 漂移要尽早收掉，不要拖
