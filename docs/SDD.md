# lite-interpreter 系统设计文档（SDD）

> 文档版本：1.0  
> 最后更新：2026-05-08  
> 本文档是 lite-interpreter 后端架构与核心模块的设计说明，面向开发者和架构评审者。

---

## 1. 系统概述与设计目标

### 1.1 项目定位

lite-interpreter 是一个面向财务、会计与经营分析场景的**受控分析运行时**。它将"资料上传 → 任务路由 → 动态研究 → 代码执行 → 结果产物 → 审计回放"串成一条完整的工程闭环，而不是一个自由发挥的通用 autonomous agent。

系统的核心设计原则是：**可治理、可观测、可回放、可交付**。

### 1.2 设计目标

| 目标 | 说明 |
|------|------|
| 可治理 | 所有动态行为必须经过 Harness Governor 策略审批，不允许无约束的自由执行 |
| 可观测 | Event Bus + Event Journal 保证每一步状态变化都有迹可循 |
| 可回放 | Blackboard 持久化 + 节点级 checkpoint 支持任务中断后恢复与审计回放 |
| 可交付 | 前端消费真实 API 数据，不伪造 DAG 节点结果或统计指标 |
| 安全边界 | AST 审计 + Docker 沙箱隔离，代码执行不逃逸容器 |

### 1.3 当前成熟度

系统已完成"旧前端 → 真实 Web 前端"的产品面迁移，以及"旧公开接口 → `/api/app/*` 合同"的 API 收口。当前唯一支持的动态运行时是 DeerFlow sidecar，结构化数据输入稳定支持 CSV/TSV/JSON。

---

## 2. 架构分层详解

系统采用六层架构，从上到下依次为：产品层、产品 API 层、控制层、编排层、动态运行层、执行与知识层。

```
┌─────────────────────────────────────────────────────┐
│  Layer 1: 产品层  apps/web (React/Vite)              │
├─────────────────────────────────────────────────────┤
│  Layer 2: 产品API层  /api/app/* (Starlette/Pydantic) │
├─────────────────────────────────────────────────────┤
│  Layer 3: 控制层  Blackboard + Event Bus + Journal    │
├─────────────────────────────────────────────────────┤
│  Layer 4: 编排层  DAG Engine (静态链 + 动态链)        │
├─────────────────────────────────────────────────────┤
│  Layer 5: 动态运行层  DeerFlow Sidecar               │
├─────────────────────────────────────────────────────┤
│  Layer 6: 执行与知识层  Sandbox + KAG + SkillNet     │
└─────────────────────────────────────────────────────┘
```

### 2.1 Layer 1 — 产品层：apps/web

**技术栈**：React 18 + TypeScript + Vite + React Router + TanStack Query + Tailwind CSS

**主要页面**：

- `/analyses`：分析总览，展示最近分析状态与快速入口
- `/analyses/new`：新建分析，选择资料与提问
- `/analyses/:analysisId`：分析详情，支持业务视图 / 运行时视图切换
- `/assets`：资料库管理
- `/methods`：查看沉淀方法（SkillNet 产物）
- `/audit`：治理与审计记录
- `/settings/session`：切换 API 地址与 Bearer Token

前端只消费 `/api/app/*` 合同，所有展示数据来自真实 API 响应，不伪造内部状态。

### 2.2 Layer 2 — 产品 API 层

**入口**：`src/api/main.py`（Starlette ASGI 应用）

**核心模块**：

| 文件 | 职责 |
|------|------|
| `routers/app_router.py` | 定义 `/api/app/*` 路由，处理 analyses/assets/methods/audit 端点 |
| `app_schemas.py` | Pydantic 请求/响应模型，定义 API 合同 |
| `app_presenters.py` | 将内部 Blackboard 状态投影为前端可消费的 DTO |
| `auth.py` | Bearer Token 认证中间件，`AuthContext` 携带 tenant/workspace/role |
| `services/task_flow_service.py` | 任务流服务：创建分析 → 启动 DAG → 投影结果 |
| `services/asset_service.py` | 资料上传与管理服务 |

**关键类**：

- `AuthContext`：认证上下文，包含 `token`、`subject`、`tenant_id`、`workspace_id`、`role`、`grants`
- `AuthGrant`：权限授权单元，`(tenant_id, workspace_id)` 二元组
- `TaskFlowService`：编排任务创建与状态查询的门面，调用 `GlobalBlackboard` 和 `ExecutionBlackboard`

**API 合同**：

```
GET  /api/app/session                     → 会话 bootstrap
GET  /api/app/analyses                    → 分析列表（分页）
POST /api/app/analyses                    → 创建分析
GET  /api/app/analyses/{id}               → 分析详情
GET  /api/app/analyses/{id}/events        → 事件流
GET  /api/app/analyses/{id}/outputs/{oid} → 产物下载
GET  /api/app/assets                      → 资料列表
POST /api/app/assets                      → 上传资料
GET  /api/app/methods                     → 方法列表
GET  /api/app/audit                       → 审计记录
```

### 2.3 Layer 3 — 控制层：Blackboard + Event Bus + Event Journal

控制层是系统的**状态事实源**，所有模块通过 Blackboard 读写状态，通过 Event Bus 传播变更。

#### 2.3.1 Blackboard 体系

| 类 | 文件 | 职责 |
|----|------|------|
| `GlobalBlackboard` | `blackboard/global_blackboard.py` | 全局单例，管理任务生命周期（创建/状态更新/归档），子黑板注册中心 |
| `ExecutionBlackboard` | `blackboard/execution_blackboard.py` | 单任务执行状态，存储 DAG 节点 checkpoint、动态链状态、治理决策日志 |
| `KnowledgeBlackboard` | `blackboard/knowledge_blackboard.py` | 知识状态：检索计划、证据包、上下文快照 |
| `MemoryBlackboard` | `blackboard/memory_blackboard.py` | 任务级记忆：历史交互、偏好、累积上下文 |
| `BaseSubBlackboard` | `blackboard/base_blackboard.py` | 子黑板抽象基类，定义 `board_name`、`read`/`write`/`persist` 接口 |

**GlobalBlackboard 核心设计**：

- 线程安全：使用 `threading.RLock` 保护所有状态读写
- 持久化优先：每次状态变更后通过 `StateRepo.merge_blackboard_sections` 写入 Postgres
- 多实例感知：读取时检查持久层是否有更新状态（支持租约/多进程场景）
- 幂等创建：支持 `idempotency_key` + `request_fingerprint` 防止重复创建任务
- 状态机：`PENDING → ROUTING → ANALYZING → CODING → EXECUTING → SUCCESS/FAILED → ARCHIVED`

**TaskGlobalState 关键字段**：

```python
class TaskGlobalState(BaseModel):
    task_id: str
    tenant_id: str
    workspace_id: str
    input_query: str
    global_status: GlobalStatus        # 枚举：PENDING/ROUTING/ANALYZING/.../SUCCESS/FAILED
    sub_status: str | None
    failure_type: str | None
    error_message: str | None
    max_retries: int
    current_retries: int
    idempotency_key: str | None
    request_fingerprint: str | None
    updated_at: datetime
```

#### 2.3.2 Event Bus

**类**：`AsyncEventBus`（`common/event_bus.py`）

- 全局单例，后台独立线程运行 asyncio 事件循环
- 发布-订阅模式，支持按 `EventTopic` 精准订阅和全局订阅
- 非阻塞发布：`publish()` 将事件放入 asyncio Queue，后台异步分发
- 线程安全：使用 `threading.Lock` 保护订阅者列表
- 隐私保护：发布前通过 `mask_payload` 自动脱敏 PII

**Event 数据模型**：

```python
@dataclass
class Event:
    event_id: str
    topic: EventTopic       # UI_TASK_CREATED / UI_TASK_STATUS_UPDATE / SYS_TASK_FINISHED / ...
    tenant_id: str
    task_id: str
    workspace_id: str
    payload: dict[str, Any]
    timestamp: datetime
    trace_id: str
```

#### 2.3.3 Event Journal

`EventJournal`（`common/event_journal.py`）是事件的持久化追加日志，每次 `event_bus.publish` 时同步写入 Journal，用于审计回放和故障恢复。

### 2.4 Layer 4 — 编排层：DAG Engine

**核心文件**：`dag_engine/dag_graph.py`

DAG Engine 是系统的**主流程 owner**，负责将任务编排为有序的节点执行链。

#### 2.4.1 静态链（Static Flow）

静态链是确定性的节点序列，由 `_execute_static_flow()` 驱动：

```
Router → DataInspector → KAGRetriever → ContextBuilder → Analyst
       → StaticEvidence → EvidenceCompiler → Coder → Auditor
       → [Debugger → Auditor] → Executor → [Debugger → Auditor]
       → SkillHarvester → Summarizer
```

**节点职责**：

| 节点 | 文件 | 职责 |
|------|------|------|
| `RouterNode` | `nodes/router_node.py` | 任务路由：根据复杂度评分决定走静态链还是动态链 |
| `DataInspector` | `nodes/data_inspector.py` | 结构化数据探查：读取 CSV/TSV/JSON，生成数据概况 |
| `KAGRetriever` | `nodes/kag_retriever.py` | 知识检索：调用 KAG QueryEngine 获取相关证据 |
| `ContextBuilder` | `nodes/context_builder_node.py` | 上下文构建：压缩、选择、格式化检索结果 |
| `AnalystNode` | `nodes/analyst_node.py` | 分析规划：根据数据和上下文生成分析计划 |
| `CoderNode` | `nodes/coder_node.py` | 代码生成：根据分析计划生成 Python 代码 |
| `AuditorNode` | `nodes/auditor_node.py` | 代码审计：AST 静态分析，检查安全与质量 |
| `DebuggerNode` | `nodes/debugger_node.py` | 调试修复：根据执行错误修复代码 |
| `ExecutorNode` | `nodes/executor_node.py` | 沙箱执行：在 Docker 容器中运行代码 |
| `SummarizerNode` | `nodes/summarizer_node.py` | 结果汇总：生成最终分析报告 |
| `DynamicSwarmNode` | `nodes/dynamic_swarm_node.py` | 动态链入口：委托 DeerFlow 执行动态研究 |
| `SkillHarvesterNode` | `nodes/skill_harvester_node.py` | 技能沉淀：从执行结果中提取可复用技能 |

#### 2.4.2 动态链（Dynamic Flow）

当 Router 判定任务复杂度超过阈值时，进入动态链：

```
Router → DynamicSwarm → [DeerFlow Sidecar] → 回流静态链
```

动态链的核心设计原则：**DAG 仍是 owner，DeerFlow 只是受控的动态研究 sidecar**。

#### 2.4.3 Checkpoint 机制

每个节点执行前后通过 `_run_checkpointed_node()` 写入 `ExecutionBlackboard`：

```python
# 执行前：标记 running
checkpoints[node_name] = {"status": "running", "started_at": ..., "attempt_count": N+1}

# 执行后：标记 completed + 存储 output_patch
checkpoints[node_name] = {"status": "completed", "completed_at": ..., "output_patch": ...}

# 异常时：标记 failed + 记录 error
checkpoints[node_name] = {"status": "failed", "failed_at": ..., "error": str(exc)}
```

这使得任务可以在任意节点中断后恢复，也支持跳过已完成节点（`output_patch` 回放）。

### 2.5 Layer 5 — 动态运行层：DeerFlow Sidecar

| 类 | 文件 | 职责 |
|----|------|------|
| `DynamicSupervisor` | `dynamic_engine/supervisor.py` | 动态运行监督：构建 TaskEnvelope、评估治理策略、准备 DeerFlow 请求 |
| `DynamicRunPlan` | `dynamic_engine/supervisor.py` | 不可变数据类：封装一次动态运行的完整控制面 bundle |
| `DeerflowBridge` | `dynamic_engine/deerflow_bridge.py` | DeerFlow 通信桥：发送任务请求、接收研究轨迹 |
| `RuntimeBackends` | `dynamic_engine/runtime_backends.py` | 运行时后端抽象：管理不同动态运行时的适配 |
| `TraceNormalizer` | `dynamic_engine/trace_normalizer.py` | 轨迹归一化：将 DeerFlow 返回的研究轨迹转换为标准格式 |
| `DynamicContextEnvelope` | `dynamic_engine/blackboard_context.py` | 上下文信封：构建注入 DeerFlow 的权威上下文 |

**DynamicSupervisor.prepare() 流程**：

1. 构建 `TaskEnvelope`（任务元数据 + 治理配置）
2. 构建 `ExecutionIntent`（路由决策：static_flow / dynamic_flow）
3. 调用 `HarnessGovernor.evaluate_dynamic_request()` 进行治理审批
4. 如果被拒绝，返回 `denied_patch`
5. 如果通过，构建 `DynamicContextEnvelope` + `DeerflowTaskRequest`

**设计约束**：

- DeerFlow 不可用时返回 `unavailable` 语义，不悄悄回退
- 最终 Python 执行边界仍在本地 Sandbox，不交给 DeerFlow
- 动态研究完成后必须回流静态链继续执行

### 2.6 Layer 6 — 执行与知识层

#### 2.6.1 Sandbox：安全执行环境

| 类 | 文件 | 职责 |
|----|------|------|
| `audit_code()` | `sandbox/ast_auditor.py` | AST 静态审计：解析代码 AST，检查高风险模块/内建函数/方法调用 |
| `DockerExecutor` | `sandbox/docker_executor.py` | Docker 执行器：创建容器、挂载数据、执行代码、收集结果 |
| `ExecutionReporting` | `sandbox/execution_reporting.py` | 执行报告：记录执行时长、资源消耗、输出产物 |
| `SecurityPolicy` | `sandbox/security_policy.py` | 安全策略：定义高风险模块列表、容器资源限制 |

**AST 审计流程**：

1. 输入校验（代码长度、租户 ID）
2. `ast.parse()` 解析代码为 AST
3. 遍历 AST 节点，检查：
   - 高风险模块导入（`os`、`subprocess`、`socket` 等）
   - 高风险内建函数（`eval`、`exec`、`__import__` 等）
   - 高风险方法调用（`__subclasses__`、`__globals__` 等）
4. 生成 `AuditResult`（通过/拒绝 + 风险详情）

**Docker 执行流程**：

1. `prepare_sandbox_run()`：准备容器配置（镜像、卷挂载、资源限制）
2. `start_sandbox_container_impl()`：启动容器
3. `wait_for_container_exit()`：等待执行完成（带超时）
4. `collect_container_logs()`：收集 stdout/stderr
5. `cleanup_sandbox_run()`：清理容器和临时文件

#### 2.6.2 KAG：知识增强生成

KAG（Knowledge-Augmented Generation）分为四个子模块：

**Builder（知识构建）**：

| 类 | 职责 |
|----|------|
| `Chunker` | 文档分块：按 token 数切分，支持父子块关系 |
| `EntityExtractor` | 实体抽取：使用 LLM 从文本中提取命名实体 |
| `RelationExtractor` | 关系抽取：提取实体间关系（语义/时序/因果/实体） |
| `Embedding` | 向量化：调用 Embedding 模型生成向量表示 |
| `Fusion` | 融合：将抽取结果合并到知识图谱 |
| `Orchestrator` | 编排：协调 Builder 各步骤的执行顺序 |

**Retriever（知识检索）**：

| 类 | 职责 |
|----|------|
| `QueryEngine` | 统一查询入口：分析查询意图，选择检索策略 |
| `HybridSearch` | 混合检索：融合 BM25 + 向量 + 图谱结果（RRF 排序） |
| `BM25Search` | 关键词检索：基于倒排索引的精确匹配 |
| `GraphSearch` | 图谱检索：基于 Neo4j 的关系遍历 |
| `SPLADESearch` | 稀疏检索：基于 SPLADE 模型的语义匹配 |
| `Rerank` | 重排序：Cross-encoder 精排 |
| `Dedup` | 去重：基于语义相似度的去重 |

**Context（上下文管理）**：

| 类 | 职责 |
|----|------|
| `Compressor` | 压缩：按 token 预算压缩检索结果 |
| `Selector` | 选择：按 RRF 策略选择最相关片段 |
| `Formatter` | 格式化：将上下文转换为 LLM 可消费的格式 |

**Compiler（知识编译）**：

| 类 | 职责 |
|----|------|
| `KnowledgeCompilerService` | 编译服务：管理知识图谱的编译与查询 |
| `KnowledgeSpecParser` | ANTLR 解析器：解析知识规范 DSL |
| `Evidence` | 证据模型：结构化证据的表示 |

#### 2.6.3 SkillNet：技能沉淀网络

| 类 | 文件 | 职责 |
|----|------|------|
| `SkillHarvester` | `skillnet/skill_harvester.py` | 技能收获：从执行轨迹中提取可复用技能候选 |
| `SkillValidator` | `skillnet/skill_validator.py` | 技能校验：验证技能的有效性和安全性 |
| `SkillPromoter` | `skillnet/skill_promoter.py` | 技能提升：将验证通过的技能提升为预设技能 |
| `SkillRetriever` | `skillnet/skill_retriever.py` | 技能检索：根据查询匹配已有技能 |
| `DynamicSkillAdapter` | `skillnet/dynamic_skill_adapter.py` | 动态适配：将动态链执行结果转换为技能候选 |
| `SkillDescriptor` | `skillnet/skill_schema.py` | 技能描述符：技能的结构化表示 |

**预设技能类别**（`skillnet/preset_skills/`）：

- `visualization_skills`：可视化技能
- `stats_skills`：统计分析技能
- `data_clean_skills`：数据清洗技能
- `compliance_skills`：合规检查技能

---

## 3. 核心数据流

### 3.1 分析创建 → 执行 → 结果投影 → 前端消费

```
[前端] POST /api/app/analyses
  │
  ▼
[TaskFlowService.create_analysis()]
  │ 调用 GlobalBlackboard.create_task()
  │   → 生成 task_id, 初始化 TaskGlobalState
  │   → 发布 UI_TASK_CREATED 事件
  │   → 持久化到 Postgres
  │
  ▼
[TaskFlowService.start_analysis()]
  │ 提交到 TASK_FLOW_EXECUTOR 线程池
  │ 调用 dag_graph.run(task_id, nodes)
  │
  ▼
[DAG Engine 静态链]
  │ Router → DataInspector → KAGRetriever → ContextBuilder
  │ → Analyst → Coder → Auditor → Executor → Summarizer
  │ 每个节点执行后更新 ExecutionBlackboard checkpoint
  │ 每次状态变更通过 EventBus 发布事件
  │
  ▼
[EventBus 分发事件]
  │ → EventJournal 持久化
  │ → SSE 推送给前端（实时进度）
  │ → 监控订阅者（告警）
  │
  ▼
[前端] GET /api/app/analyses/{id}
  │ AppPresenters 将 Blackboard 状态投影为 DTO
  │ 返回：status, progress, outputs, warnings
  │
  ▼
[前端] GET /api/app/analyses/{id}/events
  │ 返回该任务的所有事件（分页）
  │
  ▼
[前端] GET /api/app/analyses/{id}/outputs/{oid}
  │ 下载分析产物（CSV/图表/报告）
```

### 3.2 动态研究回流

```
[Router] complexity_score > threshold
  │
  ▼
[DynamicSwarmNode]
  │ DynamicSupervisor.prepare()
  │   → HarnessGovernor 审批
  │   → 构建 DeerflowTaskRequest
  │
  ▼
[DeerFlow Sidecar] 执行动态研究
  │ 返回研究轨迹 + resume_overlay
  │
  ▼
[TraceNormalizer] 归一化轨迹
  │
  ▼
[DAG Engine] 回流静态链
  │ EvidenceCompiler → MaterialRefresh → Coder → ...
```

---

## 4. 模块间依赖关系

```
┌───────────────────────────────────────────────────────────────┐
│                          API 层                                │
│  TaskFlowService ──→ GlobalBlackboard                         │
│                  ──→ ExecutionBlackboard                       │
│                  ──→ AssetService                              │
│  AppRouter ──→ TaskFlowService                                │
│           ──→ AppPresenters ──→ Blackboard (read)             │
│  AuthMiddleware ──→ AuthContext                                │
└───────────────────────────────┬───────────────────────────────┘
                                │ 调用
                                ▼
┌───────────────────────────────────────────────────────────────┐
│                        DAG Engine                              │
│  dag_graph.run() ──→ 各 Node 函数                             │
│  RouterNode ──→ DynamicSupervisor (判断是否走动态链)          │
│  DynamicSwarmNode ──→ DynamicSupervisor.prepare()             │
│                    ──→ DeerflowBridge                          │
│  各 Node ──→ ExecutionBlackboard (checkpoint)                 │
│           ──→ EventBus (状态变更通知)                         │
│           ──→ LLMClient (LLM 调用)                           │
└───────────────────────────────┬───────────────────────────────┘
                                │ 调用
                    ┌───────────┼───────────┐
                    ▼           ▼           ▼
┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐
│    Sandbox        │ │      KAG         │ │    SkillNet      │
│ ASTAuditor        │ │ QueryEngine      │ │ SkillHarvester   │
│ DockerExecutor    │ │ HybridSearch     │ │ SkillValidator   │
│ ExecReporting     │ │ BM25/Graph/SPLADE│ │ SkillPromoter    │
│ SecurityPolicy    │ │ Rerank/Dedup     │ │ SkillRetriever   │
│                   │ │ Context/*        │ │ DynamicAdapter   │
│                   │ │ Builder/*        │ │                  │
│                   │ │ Compiler/*       │ │                  │
└────────┬──────────┘ └────────┬─────────┘ └────────┬─────────┘
         │                     │                     │
         ▼                     ▼                     ▼
┌───────────────────────────────────────────────────────────────┐
│                      Storage 层                                │
│  PostgresDBClient ──→ StateRepo / AuditRepo                   │
│  VectorClient ──→ Qdrant (向量检索)                           │
│  GraphClient ──→ Neo4j (图谱检索)                             │
│  KnowledgeRepo / MemoryRepo                                   │
└───────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌───────────────────────────────────────────────────────────────┐
│                    Common / Harness                            │
│  EventBus (全局事件分发)                                      │
│  EventJournal (事件持久化)                                    │
│  LLMClient (统一 LLM 调用)                                   │
│  HarnessGovernor (治理策略)                                   │
│  ControlPlane (控制面契约)                                    │
│  CapabilityRegistry (能力注册)                                │
│  TaskEnvelope / ExecutionIntent / EvidencePacket (契约模型)   │
└───────────────────────────────────────────────────────────────┘
```

---

## 5. 存储架构

系统采用三存储引擎分离架构，各司其职：

### 5.1 Postgres — 状态存储

**客户端**：`storage/postgres_client.py` → `PostgresDBClient`

**核心表**：

| 表 | 职责 |
|----|------|
| `kag_doc_chunks` | 文档分块全文与版本 |
| `blackboard_states` | Blackboard 持久化（JSON 格式存储 TaskGlobalState、ExecutionData 等） |
| `structured_data_catalog` | 结构化数据目录 |
| `task_state` | 任务状态基座 |

**Repository 层**：

- `StateRepo`：Blackboard 状态的 CRUD，支持 `merge_blackboard_sections` 增量更新
- `AuditRepo`：审计记录的存储与查询
- `MemoryRepo`：任务级记忆的存储

### 5.2 Qdrant — 向量存储

**客户端**：`storage/vector_client.py` → `VectorClient`

**用途**：

- 存储文档分块的向量表示
- 支持语义相似度检索（cosine / dot / L2）
- 配置：`EMBEDDING_DIM`（默认 1536）、`QDRANT_HOST`、`QDRANT_PORT`

### 5.3 Neo4j — 图谱存储

**客户端**：`storage/graph_client.py` → `GraphClient`

**用途**：

- 存储知识图谱（实体 + 关系）
- 支持图遍历检索（`GraphSearch`）
- 图谱类型：semantic / temporal / causal / entity
- 配置：`NEO4J_URI`、`NEO4J_USER`、`NEO4J_PASSWORD`

### 5.4 数据流

```
资料上传 → Chunker 分块 → Postgres (全文) + Qdrant (向量)
                        → EntityExtractor + RelationExtractor → Neo4j (图谱)

查询时：QueryEngine → HybridSearch(BM25 + Qdrant + Neo4j) → Rerank → Context
```

---

## 6. 认证与授权模型

### 6.1 认证机制

**Bearer Token 认证**（`api/auth.py`）：

- 所有 `/api/app/*` 端点（除 `/health`）需要 Bearer Token
- Token 配置通过环境变量 `API_AUTH_TOKENS_JSON` 注入
- 前端通过 `/api/app/session` 完成会话 bootstrap

**AuthContext 数据模型**：

```python
@dataclass(frozen=True)
class AuthContext:
    token: str
    subject: str
    tenant_id: str
    workspace_id: str
    role: str = "operator"       # viewer / operator / admin
    grants: tuple[AuthGrant, ...] = ()
    auth_type: str = "token"
```

### 6.2 授权模型

**角色层级**：

```python
ROLE_HIERARCHY = {
    "viewer": 10,    # 只读
    "operator": 20,  # 操作
    "admin": 30,     # 管理
}
```

**权限粒度**：

- 每个 Token 绑定 `tenant_id` + `workspace_id` + `role`
- 支持多 `AuthGrant`：一个 Token 可访问多个 tenant/workspace 组合
- API 层通过 `require_auth()` 中间件校验，支持最低角色要求

### 6.3 多租户隔离

- 所有数据操作都携带 `tenant_id` + `workspace_id`
- 资料上传、产物下载限制在当前 tenant/workspace 范围内
- Blackboard 按 `(tenant_id, task_id)` 隔离状态

---

## 7. 错误处理与容错设计

### 7.1 分层异常体系

```
SandboxBaseError
  ├── AuditFailError          # AST 审计失败
  ├── SyntaxParseError        # 语法解析错误
  ├── CodeExecError           # 代码执行错误
  ├── DockerOperationError    # Docker 操作失败
  ├── ExecTimeoutError        # 执行超时
  └── InputValidationError    # 输入校验失败

BlackboardBaseError
  ├── TaskNotExistError       # 任务不存在
  ├── SubBoardNotRegistered   # 子黑板未注册
  └── StatusUpdateError       # 状态更新失败

DAGBaseError
  └── TaskLeaseLostError      # 任务租约丢失
```

### 7.2 容错机制

**节点级重试**：

- `MAX_RETRIES`（默认 3）：Coder → Debugger → Auditor 循环的最大次数
- 每次重试记录在 `ExecutionBlackboard` checkpoint 中

**任务租约**：

- `TASK_LEASE_TTL_SECONDS`（默认 60s）：任务执行锁的 TTL
- `TASK_LEASE_HEARTBEAT_SECONDS`（默认 20s）：心跳间隔
- 防止多进程同时执行同一任务

**中断恢复**：

- 服务重启后通过 `GlobalBlackboard.list_unfinished_tasks()` 恢复未完成任务
- 节点 checkpoint 机制支持从断点继续执行
- `WAITING_FOR_HUMAN` 状态不自动恢复，需要前端用户主动触发

**治理拒绝**：

- `HarnessGovernor` 可拒绝动态运行请求
- 拒绝时返回 `denied_patch`，任务标记为 `denied` 状态

### 7.3 错误投影

API 层统一返回结构化错误信封：

```python
{
    "error": {
        "code": "EXECUTION_TIMEOUT",
        "message": "沙箱执行超时",
        "details": {...},
        "trace_id": "..."
    }
}
```

---

## 8. 配置管理

### 8.1 配置层次

```
.env                    # 环境变量（敏感信息，不入版本控制）
.env.example            # 环境变量模板
config/settings.py      # Python 配置（读取环境变量，提供默认值）
config/harness_policy.yaml    # 治理策略
config/analysis_runtime.yaml  # 运行时策略
config/sandbox_config.py      # 沙箱配置
config/deerflow_sidecar.yaml  # DeerFlow 配置
```

### 8.2 关键配置项

| 配置 | 默认值 | 说明 |
|------|--------|------|
| `API_AUTH_REQUIRED` | `True` | 是否启用认证 |
| `API_AUTH_TOKENS_JSON` | `{}` | Token 映射（JSON） |
| `DEERFLOW_RUNTIME_MODE` | `sidecar` | 动态运行时模式 |
| `DEERFLOW_SIDECAR_URL` | `""` | DeerFlow sidecar 地址 |
| `MAX_RETRIES` | `3` | 节点最大重试次数 |
| `CONTEXT_BUDGET_TOKENS` | `4000` | 上下文 token 预算 |
| `CHUNK_SIZE` | `800` | 分块大小 |
| `EMBEDDING_DIM` | `1536` | 向量维度 |
| `TASK_LEASE_TTL_SECONDS` | `60` | 任务租约 TTL |

### 8.3 配置变更约定

修改配置时必须同步更新三处：

1. `.env.example`
2. `config/settings.py`
3. `docs/how-to/deployment.md`

---

## 9. 测试策略

### 9.1 测试分层

| 层级 | 目录 | 工具 | 覆盖范围 |
|------|------|------|----------|
| 单元测试 | `tests/unit/` | pytest | 单个函数/类的逻辑 |
| 集成测试 | `tests/integration/` | pytest + Docker | 模块间交互、存储层 |
| 契约测试 | `tests/` | pytest | API 合同、文档一致性 |
| 前端测试 | `apps/web/` | ESLint + Build | 代码规范 + 构建验证 |
| 评估测试 | `src/evals/` | 自定义 runner | 端到端分析质量 |

### 9.2 关键验证命令

```bash
# 后端全量测试
conda run -n lite_interpreter python -m pytest -q

# 文档一致性
conda run -n lite_interpreter python -m pytest -q tests/test_docs_consistency.py

# 前端验证
cd apps/web && npm run lint && npm run build

# 代码规范
conda run -n lite_interpreter python -m ruff check src tests scripts config
```

### 9.3 评估框架

`src/evals/` 提供端到端评估能力：

- `cases.py`：定义评估用例（输入 → 期望输出）
- `runner.py`：执行评估用例
- `run.py`：CLI 入口

---

## 10. 关键设计决策与权衡

### 10.1 Blackboard 作为单一状态源

**决策**：所有模块通过 Blackboard 读写状态，不允许隐式状态传递。

**权衡**：
- ✅ 状态可追溯、可持久化、可回放
- ✅ 模块间解耦，只需依赖 Blackboard 接口
- ❌ 增加了一次间接层，性能略有开销
- ❌ 需要严格的线程安全设计

### 10.2 DAG 为主、DeerFlow 为辅

**决策**：DAG Engine 始终是流程 owner，DeerFlow 只作为受控的动态研究 sidecar。

**权衡**：
- ✅ 主流程确定性强，可预测、可审计
- ✅ 动态能力按需启用，不影响核心链路稳定性
- ❌ 动态研究能力受限于预设的 step 和 token 预算
- ❌ 需要维护静态链与动态链的回流衔接逻辑

### 10.3 AST 审计 + Docker 沙箱双重隔离

**决策**：代码执行前先做 AST 静态审计，通过后在 Docker 容器中执行。

**权衡**：
- ✅ 双层防护，AST 拦截明显恶意代码，Docker 隔离运行时风险
- ✅ 审计结果可解释（`SecurityExplainer`）
- ❌ AST 审计可能有误报（过于保守的规则）
- ❌ Docker 容器启动有额外延迟

### 10.4 三存储引擎分离

**决策**：Postgres 存状态、Qdrant 存向量、Neo4j 存图谱，不试图用单一存储解决所有问题。

**权衡**：
- ✅ 每个引擎做自己最擅长的事
- ✅ 可独立扩展和优化
- ❌ 运维复杂度增加（三个有状态服务）
- ❌ 跨存储的事务一致性需要应用层保证

### 10.5 Event Bus 异步解耦

**决策**：使用独立线程的 asyncio 事件循环处理事件分发。

**权衡**：
- ✅ 事件发布不阻塞主流程
- ✅ 订阅者可以是同步或异步函数
- ❌ 增加了调试复杂度（异步栈追踪）
- ❌ 需要处理事件循环生命周期管理

### 10.6 节点级 Checkpoint 而非全局快照

**决策**：每个 DAG 节点独立 checkpoint，而非对整个任务做全局快照。

**权衡**：
- ✅ 粒度细，可以跳过已完成节点恢复
- ✅ 存储开销小，只记录增量
- ❌ 节点间的状态依赖需要通过 `output_patch` 显式传递
- ❌ Checkpoint 格式需要向前兼容

---

> 本文档随代码演进持续更新。如有疑问，请参阅 `docs/reference/project-status.md` 获取最新状态。
