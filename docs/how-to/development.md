# lite-interpreter 开发手册

本文件是 **How-to Guide**：面向日常开发者，回答“改东西前看什么、怎么改、改完至少验证什么”。

当前成熟度、测试基线与已知热点统一以 `docs/reference/project-status.md` 为准。

## 1. 开发前先统一心智

这个项目最重要的不是“多做几个功能”，而是让以下边界始终稳定：

1. DAG 是主流程 owner
2. DeerFlow 只是受控动态研究 runtime
3. Sandbox 仍是最终代码执行边界
4. Blackboard 是状态事实源
5. Web 前端只消费 `/api/app/*` 合同，不再回头依赖旧公开接口

## 2. 先读哪些文件

### 2.1 改产品面（前端 / app-facing API）

先读：

- `docs/explanation/architecture.md`
- `apps/web/src/app/App.tsx`
- `apps/web/src/lib/api.ts`
- `src/api/routers/app_router.py`
- `src/api/app_schemas.py`
- `src/api/app_presenters.py`

适用问题：

- 页面字段怎么来的
- 前端为什么只用 `/api/app/*`
- 某个产品读模型应该在哪一层拼装

### 2.2 改控制面

先读：

- `src/common/contracts.py`
- `src/blackboard/schema.py`
- `src/blackboard/global_blackboard.py`
- `src/blackboard/execution_blackboard.py`
- `src/common/event_journal.py`

适用问题：

- 为什么任务状态不一致
- 为什么事件回放不对
- 为什么 API 读模型拿不到正确终态

### 2.3 改静态链 / 动态链

先读：

- `src/dag_engine/dag_graph.py`
- `src/dag_engine/graphstate.py`
- `src/dag_engine/nodes/*`
- `src/dynamic_engine/supervisor.py`
- `src/dynamic_engine/deerflow_bridge.py`

适用问题：

- router 为什么这样分流
- dynamic 研究结果如何回流静态链
- 最终摘要为何与真实状态不一致

### 2.4 改执行层 / 安全边界

先读：

- `src/sandbox/ast_auditor.py`
- `src/sandbox/docker_executor.py`
- `src/sandbox/execution_reporting.py`
- `src/harness/*`

适用问题：

- 执行为什么被拒绝
- AST 风险为什么判成这样
- 产物、日志、结果为什么没正确落库/投影

### 2.5 改知识 / 方法沉淀

先读：

- `src/kag/*`
- `src/skillnet/*`
- `src/memory/memory_service.py`
- `src/storage/repository/knowledge_repo.py`
- `src/storage/repository/memory_repo.py`

## 3. 日常改动原则

默认遵守：

1. 不绕开 Blackboard 传隐式状态
2. 不绕开 Harness 直接触发执行
3. 不把 DeerFlow 当系统 owner
4. 不为了“看起来支持更多”恢复假支持
5. 涉及行为变化的修复，优先补回归测试
6. 涉及产品面合同变化，必须同时更新文档与测试

## 4. 推荐改动流程

### 4.1 改动前

1. 先确认这是产品流问题、控制面一致性问题、执行安全问题，还是文档/配置漂移问题
2. 找到已有测试和相关文档
3. 如果会改行为，先补一个能锁住旧问题的测试

### 4.2 改动中

- 优先做局部拆分和边界修正，不做无根据的大重构
- 节点保持编排职责，复杂拼装逻辑尽量下沉到 service / helper / repository
- 对前端和 API 合同改动时，优先保持字段含义稳定
- 改动配置契约时，同步更新 `.env.example`、`config/settings.py` 和部署文档

### 4.3 改动后

至少执行：

```bash
cd /home/linsir365/projects/lite-interpreter
conda run -n lite_interpreter python -m ruff check src tests scripts config
conda run -n lite_interpreter python -m pytest -q
```

如果改了 Web 前端，再补：

```bash
cd /home/linsir365/projects/lite-interpreter/apps/web
npm run lint
npm run build
```

## 5. 常用命令

### 后端检查

```bash
make lint-all
make test
```

### 前端检查

```bash
cd apps/web
npm run lint
npm run build
```

### 关键 smoke / readiness

```bash
python3 scripts/check_hybrid_readiness.py
conda run -n lite_interpreter python scripts/smoke_dashscope_litellm.py
conda run -n lite_interpreter python scripts/smoke_deerflow_bridge.py
```

## 6. 改不同区域时最容易踩坑的点

### 6.1 改前端时

- 不要重新引入旧 task / execution 风格公开接口依赖
- 不要在浏览器里绕开 `Authorization` header 改走 query token
- 不要让页面自己拼第二套状态真相

### 6.2 改 app-facing API 时

- 不要把内部实体原样泄露给前端
- presenter / schema / frontend type 必须同步看
- 任何字段删改都要检查 `apps/web/src/lib/types.ts` 与页面消费点

### 6.3 改配置时

- `.env.example`、`config/settings.py`、`docs/how-to/deployment.md` 必须同步
- 默认值要服务当前前端/API 现实，不要继续保留旧产品面时代的残留默认项

### 6.4 改文档时

- `docs/reference/project-status.md` 负责状态与验证基线
- 其它文档引用它，不要各自硬编码测试通过数字
- 新文档要先回答“它到底只负责哪一个问题”

## 7. 当前最需要警惕的热点

1. `src/sandbox/docker_executor.py` 仍然偏大
2. `src/dag_engine/nodes/static_codegen.py` 仍然偏模板化
3. app-facing 合同已经稳定，但新字段一旦漂移，前后端都会一起坏
4. 资料、产物、方法、审计这些辅助页已经成型，但不应抢走主分析链路的注意力
