# lite-interpreter

`lite-interpreter` 是一个面向数据分析任务的、受控且可观测的智能执行运行时原型。它不是一个让 agent 自由发挥的通用自治系统，而是一个把路由、知识检索、动态研究、代码生成、审计、执行、事件回放和技能沉淀都纳入工程控制面的项目。

## 项目定位

这个项目要解决的问题，不是“让模型看起来很聪明”，而是让一条真实的数据分析任务链路满足下面几个要求：

- 能判断任务该走静态链还是动态研究链
- 能把结构化数据、业务文档、检索证据和治理决策纳入统一状态
- 能把最终代码执行留在本地受控 sandbox，而不是把执行权交给动态 runtime
- 能把执行轨迹、产物、tool-call、最终回答统一暴露给 API 和前端
- 能把成功经验沉淀为可复用 skill，而不是每次重新烧 token

一句话总结：

> 宏观用确定性 DAG 托底，微观用 DeerFlow sidecar 做受控动态研究，最终代码执行留在本地 sandbox，所有状态回写 Blackboard。

## 当前架构

当前项目由五个主面组成：

1. **控制面**
   - `GlobalBlackboard / ExecutionBlackboard / KnowledgeBlackboard / MemoryBlackboard`
   - `EventBus / EventJournal`
   - `TaskEnvelope / ExecutionIntent / DecisionRecord / ExecutionRecord`
   - 负责状态事实源、事件投递、回放和资源投影

2. **运行面**
   - `router -> static chain / dynamic_swarm`
   - `DynamicSupervisor -> DeerflowBridge -> TraceNormalizer`
   - 当前动态运行时只支持 **DeerFlow sidecar**，不再支持 embedded / auto 模式

3. **执行面**
   - `ast_auditor.py`
   - `docker_executor.py`
   - `sandbox_exec_tool.py`
   - 负责输入校验、AST 审计、治理决策、Docker 执行和执行记录标准化

4. **知识面**
   - `KAG Builder / Retriever / Context`
   - `KnowledgeRepo / Postgres / Qdrant / Neo4j`
   - `SkillNet / MemoryRepo`
   - 负责文档解析、知识召回、上下文压缩、技能沉淀和历史复用

5. **产品面**
   - `Analysis Workspace` 为主工作台
   - `Knowledge Assets / Skill Library / Audit Logs` 为辅助页面
   - API 提供 task/workspace/execution/runtime/diagnostics 等资源

## 当前支持的能力边界

### 动态运行时

当前唯一支持的动态运行时是 **DeerFlow sidecar**。

- 支持：动态研究、工具化检索、轨迹写回、研究结果回流静态链
- 不支持：把最终代码执行权交给 DeerFlow
- sidecar 不可用时：返回明确的 `unavailable` 语义，不再悄悄切到 embedded 或 auto 模式

### 结构化数据输入

当前静态执行链**可靠支持**以下结构化格式：

- `.csv`
- `.tsv`
- `.json`

说明：

- 项目历史上对 `.xlsx / .xls / .parquet` 有过“表面支持”，但静态 codegen 和数据嗅探链路并没有真正完成这些格式的稳定执行闭环。
- 因此当前版本对这些格式不再宣传为“直接可执行支持”。如果你要做稳定分析，建议先预转换成 `csv/tsv/json` 再上传。

### 认证与访问控制

当前 API 默认采用更保守的安全姿态：

- `API_AUTH_REQUIRED` 默认开启
- 除 `/health` 外，受保护接口按角色校验
- 不再支持通过 query string 传 `access_token`
- session login 只有在显式配置 `API_AUTH_USERS_JSON` 和 `API_SESSION_SECRET` 时才可用
- `viewer / operator / admin` 三层角色仍然保留
- 前端流式状态改为带 `Authorization` header 的 polling，不再通过浏览器 query token 建立 `EventSource`

### 执行产物暴露

当前版本对 artifact path 做了安全收口：

- 只允许暴露受控根目录内的本地产物路径（上传目录 / 输出目录）
- 允许显式的 `http/https` 远端引用
- 不再把任意绝对路径当作可预览/可下载文件直接交给前端
- 文本和图片类 artifact 现在通过 execution artifact content API 读取内容，而不是前端直接读本机路径

### Workspace 资产与任务输入

当前版本支持更明确的“workspace 资产 -> task 输入”流：

- workspace 层上传后，每个文件都有稳定 `file_sha256`
- 新建 task 时，可通过 `workspace_asset_refs` 显式挂接这些资产
- 前端工作台支持从当前 workspace 资产列表里选择要附带到新任务的输入

### 多文件上传

当前 `/api/uploads` 支持一次上传多个文件：

- 单文件上传时，响应保持原有兼容结构
- 多文件上传时，响应返回 `uploaded_files` 和 `file_count`
- 上传同时受两层大小限制约束：
  - 单文件大小上限：`UPLOAD_MAX_FILE_BYTES`
  - 单请求总大小上限：`UPLOAD_MAX_REQUEST_BYTES`

## 快速开始

### 1. 准备环境

推荐环境：

- conda env: `lite_interpreter`
- Python: `3.12`

安装依赖后，先执行：

```bash
conda run -n lite_interpreter python -m pytest -q
```

### 2. 启动 API

```bash
cd /home/linsir365/projects/lite-interpreter
conda run -n lite_interpreter python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000
```

### 3. 启动 DeerFlow sidecar

```bash
cd /home/linsir365/projects/lite-interpreter
export DEERFLOW_SIDECAR_URL=http://127.0.0.1:8765
conda run -n lite_interpreter python scripts/run_deerflow_sidecar.py --host 127.0.0.1 --port 8765
```

### 4. 启动前端

```bash
cd /home/linsir365/projects/lite-interpreter
PYTHONPATH=$(pwd) conda run -n lite_interpreter streamlit run src/frontend/app.py --browser.gatherUsageStats false
```

### 5. 常用验证命令

```bash
conda run -n lite_interpreter python -m ruff check src tests scripts config
conda run -n lite_interpreter python -m pytest -q
python3 scripts/check_hybrid_readiness.py
```

## 建议阅读顺序

第一次读仓库，建议顺序：

1. `docs/project_status.md`
2. `docs/architecture.md`
3. `directory.txt`
4. `docs/development_guide.md`
5. `docs/deployment.md`
6. `docs/testing.md`
7. `项目二.md`

## 文档索引

- `docs/project_status.md`：当前成熟度、测试基线、已知热点、明确非目标
- `docs/architecture.md`：系统结构、模块边界、主链路说明
- `docs/development_guide.md`：开发环境、改动原则、常见改动入口
- `docs/deployment.md`：依赖、环境变量、启动方式、运维要点
- `docs/testing.md`：测试分层、命令、回归要求
- `directory.txt`：仓库目录导览
- `项目二.md`：中文项目综述与下一阶段工程重点

## 当前工程判断

这个项目现在已经不是“概念验证玩具”，但也还没到“上线即产品”的程度。

它已经具备：

- 静态链 / 动态链 / sandbox / blackboard 的最小闭环
- execution / artifacts / tool-calls / diagnostics / conformance 资源层
- 前端主工作台与 API 读模型的基本联动
- 历史 skill recall 与 usage/outcome 回写能力

但你仍然应该把它视为一个**正在工程化收口的原型**。最重要的工作，不是继续堆模块，而是继续收紧边界、减少假支持、把控制面和产品面做扎实。
