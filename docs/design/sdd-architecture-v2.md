# SDD: lite-interpreter v2 架构设计文档

状态：IN PROGRESS（部分实现）
日期：2026-04-29
最后更新：2026-05-08

## 实现进度（2026-05-08）

| ADR | 状态 | 已完成 | 待完成 |
|-----|------|--------|--------|
| ADR-001 | 未开始 | — | 全部 |
| ADR-002 | 部分实现 | Router 简化为 3 层信号 → 二进制路由（`static_flow`/`dynamic_flow`）；fine routing 删除（`_maybe_refine_route_with_llm` 已移除） | `RoutingVerdict`/`RoutingDecision` 正式模型未实现；`CapabilityTier` 4 值枚举未实现；router 仍产出 `execution_intent` 而非让 analyst 决定 tier |
| ADR-003 | 部分实现 | `artifact_plan`/`verification_plan` 改为 `@computed_field`（从 `strategy_family` 派生）；`frozen=True` 已加；coder/debugger 不再写 `artifact_plan`/`verification_plan`；`ensure_artifact_plan`/`ensure_verification_plan` 已删除；`PreparedStaticCodegen`/`ExecutionStaticState`/`NodeOutputPatchState` 中对应字段已删除；`build_static_generation_bundle` 5-tuple → 3-tuple | `analysis_mode`/`research_mode`/`strategy_family`/`generator_id` 改为 `@computed_field` 从 `capability_tier` 派生（未实现）；`execution_intent` 改为 `@computed_field`（未实现）；`program_spec`/`repair_plan` 顶级 key 未删除；Instructor pipeline 未接入；`analysis_plan: str` 未删除 |
| ADR-004 | 未开始 | — | 全部 |

**注意：** 以下 ADR 正文描述的是目标设计（TARGET），不是当前实现。已完成部分在正文中用 ✅ 标注。

## 1. 设计目标与约束

### 1.1 问题陈述

lite-interpreter 有一条真实存在的主骨架（Web 前端 → `/api/app/*` 合同 → Blackboard 状态事实源 → DAG 编排 → Sandbox 执行边界），但当前被四组系统性张力持续削弱：

1. **DeerFlow 仍是外部运行时依赖，动态能力不归自己。** `dynamic_swarm_node` 本质上是对 DeerFlow sidecar HTTP streaming 的适配层，supervisor / bridge / trace_normalizer 都围绕这个外部边界设计。动态路径不是 lite-interpreter 自己的原生探索循环。
2. **路由缺乏显式能力梯度合同，且职责过重。** 当前 routing 依赖 pattern 匹配承担了"选起点"和"定路径"双重职责，而真正的能力级别判断应该由 analyst 做出。routing 应退化为粗筛——只决定起点（明显简单 / 明显开放 / 其余从静态开始），不决定后续的能力升级。
3. **`ExecutionStrategy` 不是规划权威——多主写入 + 自然语言字符串 + 双重存储。** `analyst` 产出自然语言 `analysis_plan: str`（f-string 拼接），DAG 行为仍由 preset + registry 决定。`ExecutionStrategy` 虽内嵌了 `evidence_plan`、`artifact_plan`、`verification_plan`、`program_spec`、`repair_plan`，但被 `analyst` → `coder` → `debugger` 三个节点先后覆写，coder 兼任 planner / compiler / contract builder，子计划同时作为顶级 key 重复存储在 3 个 state 类中（5 个位置存同一份数据）。同时 `analysis_mode`、`research_mode`、`strategy_family`、`generator_id` 等字段是 `capability_tier` 的派生值，不应独立存储。
4. **static codegen 双后端 + 模板驱动，不是任务自适应。** legacy renderer 与 compiler template 两套输出语义并存，artifact writer 通过字符串注入挂到 legacy 路径，输出语义分散在 registry / compiler / renderer 三处。且 coder_node 应直接按 ExecutionStrategy 生成代码，不需要独立的 codegen 节点或 registry 编译模板。
5. **产物交付面被固定 family 限死。** artifact family 与 emit kind 被 registry 固定，用户看不到任务特化的完整交付物。

### 1.2 v1 范围与优先级

按 DAG 自底向上顺序解决——先让下游节点自立，再让上游获得权威：

| 优先级 | 问题 | 理由 |
|--------|------|------|
| P0 | DeerFlow 内化为 `dynamic_exploration_node` | analyst 的下游节点不归自己，analyst 就无法成为真权威 |
| P1 | 路由能力梯度合同一等化 | 入口必须先有显式梯度，后续节点才能按合同分流 |
| P2 | `ExecutionStrategy` 单一真相源 | 补齐字段、消除双重存储、analyst 成为唯一写入者，禁止 coder/debugger 覆写 |
| P3 | static codegen 收敛到统一后端 | 去掉 legacy renderer 主入口地位，artifact writer 不再字符串注入 |
| v2 | 产物交付面任务特化 | 报告/图表/表格/诊断产物/来源引用/对账轨迹 |

### 1.3 NON-goals（v1 明确不做）

- 不删 DeerFlow 代码（先内化思想，后移除运行时）
- 不改 DAG 拓扑（先收口控制权和节点归属，后改图结构）
- 不改前端 API 和页面结构
- 不迁移数据库 / checkpoint schema（向后兼容）
- 不引入新的编排框架（不用 LangGraph / Temporal / Prefect）

### 1.4 依赖调整

v1 原约束"不增加新的外部依赖"是基于当时 DeerFlow 外部依赖 + pattern 路由的现状制定的。引入编译层后，新增依赖换取的收益远大于旧依赖的维护成本：

| 新增依赖 | 替换/补充 | 理由 |
|----------|-----------|------|
| `instructor` | 手写 `json.loads()` + 重试循环 | 一行 `response_model=ExecutionStrategy` 替代胶水代码；内置降级（`response_format` → `tool_choice`）和自动重试 |
| `tree-sitter` + `tree-sitter-python` | stdlib `ast` | 语法结构模式匹配，替代字符串黑名单；精确到行号+严重级别的风险标注 |
| `guidance` | **删除** | 当前只做 fine routing（`guidance_runner.py` 80行），ADR-002 中 fine routing 被移除后无其他用途 |

- `guidance` 在 fine routing 移除后直接删除，不再作为依赖
- DeerFlow 依赖在 ADR-001 内化稳定后整体删除
- 净依赖变化：+2 (instructor, tree-sitter) -1 (guidance) -1 (deerflow 日后) = 持平或更少

### 1.5 硬约束

- **旧 checkpoint 必须可读。** 任何 Pydantic schema 变更必须向后兼容。旧数据优先读新字段，缺失时 adapter 补。
- **旧字段不直接删除，走 migration window。** `analysis_plan` → 最晚删（挂展示层），`generation_directives` → registry 稳定后删，`next_static_steps` / `dynamic_next_static_steps` → 一起退。
- **迁移原则：先加新字段双写，再旧字段降级为 compatibility，最后删旧。**
- **`legacy_dataset_aware_generator` 不能从 Literal 直接删。** 旧 checkpoint 里 `ExecutionStrategy.strategy_family` 可能已持久化为该值，删了 Pydantic 读旧数据会 validation error。
- **测试必须持续通过。** 每次 migration step 后跑 `conda run -n lite_interpreter python -m pytest -q`。

### 1.6 编译层代码组织

新建 `src/compiler/` 作为统一编译层入口，吸收现有 KAG 编译器：

```
src/compiler/
├── __init__.py
├── plan_compiler.py          # Plan 编译: Instructor + response_model=ExecutionStrategy
├── code_compiler.py          # 代码编译: build_codegen_prompt() + LLM → sandbox code
├── code_auditor.py           # Tree-sitter 代码审计 (替代 ast_auditor.py)
└── kag/                      # ← 从 src/kag/compiler/ 整体搬迁
    ├── __init__.py
    ├── types.py
    ├── service.py
    ├── parser.py             # ANTLR 业务规则编译
    ├── graph.py              # 知识图谱白名单编译
    ├── evidence.py           # 证据材料编译
    ├── lexicon.py            # pyahocorasick 编译
    └── grammar/              # ANTLR 语法 + 生成器
```

搬迁后所有 `from src.kag.compiler import ...` → `from src.compiler.kag import ...`。

编译层统一了四种编译对象的管道模式：

| 编译器 | 输入 | 输出 | 约束机制 |
|--------|------|------|----------|
| `plan_compiler` | 用户查询 + 上下文 | `ExecutionStrategy(frozen=True)` | Instructor response_model |
| `code_compiler` | `ExecutionStrategy` + spec | Python 代码 | Prompt 约束 + Tree-sitter 审计 |
| `kag/parser` | 自然语言业务规则 | `RuleSpec/MetricSpec/FilterSpec` | pyahocorasick + ANTLR |
| `kag/graph` | EntityNode[] | `ValidatedTriple[]` | 白名单 + GraphValidator |
| `kag/evidence` | 检索结果 | `EvidenceMaterialPatch` | JSON 解析 + 去重校验 |

## 2. 架构决策记录（ADR）

### ADR-001：DeerFlow 内化 —— 统一入口、多 backend、trace 观测

**状态：** ACCEPTED / 未实现
**日期：** 2026-04-30

#### Context

当前动态路径的唯一实现是 `dynamic_swarm_node` → `DeerflowBridge` → DeerFlow sidecar HTTP streaming。这导致：

- 动态探索能力不归 lite-interpreter 自己所有
- analyst 说"走动态"等于"交给外部服务"，无法成为真正的规划权威
- 无法在 native 实现和 DeerFlow fallback 之间做可观测的切换

目标：新增 native `dynamic_exploration_node` 作为主路径，DeerFlow 降级为 fallback backend，全程可观测。

#### Decision

**1. 统一入口节点**

DAG 只看到一个 `dynamic_node`。内部按 backend 分流：

```
router → dynamic_node
           ├── NativeExplorationBackend（主路径）
           │     └── MCP gateway tool-calling loop
           │           ├── web_search / web_fetch
           │           ├── sandbox_exec
           │           └── ... 其他注册 tool
           └── DeerflowFallbackBackend（降级路径）
                 └── 复用现有 DeerflowBridge
```

- `dynamic_swarm_node` 重命名为 `dynamic_node`，保持 DAG 拓扑不变（符合 1.3 约束）
- `task_flow_service.py` 中 `"dynamic_swarm"` → `"dynamic"`，旧名保留为 alias 一个 migration window
- router 的 `destinations` 从 `"dynamic_swarm"` 改为 `"dynamic"`

**2. Backend 抽象**

```python
class DynamicBackend(Protocol):
    """单个动态执行后端的接口合同。"""
    async def run(self, state: DagState) -> DynamicResult: ...
    async def preview(self, state: DagState) -> DynamicPreview: ...

class DynamicResult(TypedDict):
    backend: Literal["native", "deerflow_fallback"]
    events: list[ExecutionEvent]
    artifacts: list[ArtifactRef]
    dynamic_overlay: DynamicResumeOverlay | None
    error: str | None
```

- `NativeExplorationBackend`：新写，内部是 MCP gateway tool-calling loop（多步探索 / 观察 / 反思 / 再规划 / 工具预算 / 轨迹采集）。不依赖任何 `deerflow` 包。
- `DeerflowFallbackBackend`：包装现有 `DeerflowBridge`，实现同一接口。不删不改原 bridge 代码。

**3. Fallback 触发条件**

Native backend 只在 **retry 耗尽** 时降级：

```
native_backend.run()
  → tool_call 失败（网络/超时/MCP gateway 不可用）
    → retry 1
      → 仍失败
        → retry N (达到 max_retries)
          → 仍失败 → 降级到 DeerflowFallbackBackend
```

- `max_retries` 默认 2，可通过 `config/settings.py` 的 `DYNAMIC_NATIVE_MAX_RETRIES` 覆盖
- 降级时发 trace 事件，携带 `reason` 和 `retry_count`
- 不在 native backend 内部做联网重试（用户明确：联网重试没用）

**4. 观测体系（Trace 事件，不改 blackboard schema）**

每次动态执行发三条 governance trace event：

| 时机 | event_type | payload |
|------|-----------|---------|
| 进入动态节点 | `governance` | `{phase: "dynamic_start", backend: "native", task_id, timestamp}` |
| Backend 切换（如有） | `governance` | `{phase: "dynamic_fallback", from: "native", to: "deerflow_fallback", reason: "retry_exhausted", retry_count: N, failed_tool: "web_search"}` |
| 动态节点结束 | `governance` | `{phase: "dynamic_end", final_backend, total_steps, artifacts_count, success}` |

这些事件走现有 `ExecutionEvent(event_type="governance", ...)` 通道，进入 `EventBus` → `TraceStore`，前端通过 diagnostics API 可查。

**不**在 blackboard schema 加 `dynamic_backend` 字段——避免为观测目的膨胀状态 schema。trace 是观测的正道，blackboard 是状态事实源。

**5. 配置变更**

`config/settings.py` 新增：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DYNAMIC_NATIVE_MAX_RETRIES` | `2` | native backend retry 上限 |
| `DYNAMIC_NATIVE_MAX_STEPS` | `6` | native tool-calling loop 最大步数 |
| `DYNAMIC_NATIVE_TIMEOUT` | `300` | native backend 总超时（秒） |
| `DYNAMIC_FALLBACK_ENABLED` | `true` | 是否允许降级到 DeerFlow |

旧的 `DEERFLOW_*` 变量全部保留不动——DeerflowFallbackBackend 仍然需要它们。

**6. 动态探索的编译层约束**

动态探索与静态 Plan 编译使用同一套编译层基础设施：

- **每步 tool call 输出**经 `plan_compiler` 编译为中间决策（探索专用 ExecutionStrategy，不写回 blackboard）
- **多轮探索循环**：观察 → 编译当前状态 → 决策下一步 → 执行 tool call → 观察 → ...
- **探索结束**：产出 `DynamicResumeOverlay` → 回流 analyst（`material_refresh`）
- **编译层同一**：动态和静态走同一套 `plan_compiler`，区别是动态多轮、中间态不冻结

#### Consequences

**变容易的事：**
- 可以在 native backend 里迭代 tool-calling 策略，不碰 DeerFlow 代码
- 线上可以通过 trace 事件精确统计 native vs fallback 的流量比例
- `DYNAMIC_FALLBACK_ENABLED=false` 可以直接切断 DeerFlow 依赖（纯 native 模式验证）
- 日后 DeerFlow 代码可以整体删除，只删 `DeerflowFallbackBackend` + `src/dynamic_engine/` 即可

**变困难的事：**
- 维护期两套 backend 并存，trace_normalizer 需要同时处理 native 和 deerflow 两种事件格式
- Native backend 的实现需要仔细对齐 DeerFlow 已验证的行为语义（多步探索、观察/反思/再规划、轨迹采集），不能只做一个简单的单次 LLM 调用
- fallback 切换时的状态连续性——native backend 已经做了 2 步探索然后失败，deerflow backend 是重头开始还是接续？v1 选择重头开始（简单，不丢信息），但浪费 token

#### Alternatives Considered

**A: 从零重写 + 直接删 DeerFlow。**
拒绝了——风险太大，没有 fallback 一旦 native 实现有问题线上全挂。

**B: 新老节点并存 + router feature flag 灰度。**
拒绝了——两个 DAG 节点做同一件事，router 逻辑变复杂，且用户明确要统一入口。

**C: Blackboard 打标观测。**
拒绝了——blackboard 是状态事实源，观测是旁路关注点。trace 事件更适合承载"走了哪条路"这类诊断信息。

### ADR-002：路由能力梯度合同一等化

**状态：** ACCEPTED / 部分实现
**日期：** 2026-04-30

> **已实现（2026-05-08）：** Router 简化为 3 层信号（意图结构/时效性/外部知识域）→ `static_flow` / `dynamic_flow` 二进制路由。`ExecutionIntent.intent` 收窄为 `Literal["static_flow", "dynamic_flow"]`。`_maybe_refine_route_with_llm` 已删除。`_DYNAMIC_SIGNALS` 硬编码关键词列表已替换为三层信号检测。
> **未实现：** `RoutingVerdict` / `RoutingDecision` 正式模型。`CapabilityTier` 4 值枚举。analyst 作为 tier 唯一决策者。`analysis_mode` / `research_mode` 等作为 `@computed_field` 从 `capability_tier` 派生。

#### Context

当前 routing 承担了两层职责：

- 粗筛起点（选 DAG 节点链）：pattern 匹配 → destinations
- 能力判断（选 tier）：pattern + optional fine routing → research_mode + intent

两层耦合导致 pattern 匹配既要做起点指派又要做能力推断。审计报告记录了典型案例：`分析当前美国的经济走向` 曾被误判为 `need_more_inputs`，只能靠往 pattern 列表里补关键词止血。

目标：routing 退化为**纯粗筛**——只决定起点（明显开放 / 其余从静态开始），能力级别判断交给 analyst。

**注意：router 不跳过 analyst。** "跳过 analyst"意味着跳过 `ExecutionStrategy` 的唯一产出者，那谁来告诉 coder 该生成什么代码？"有本地数据"不代表任务简单到不需要分析——聚合、趋势、对比、artifact 选择、联网判断，这些仍需要 analyst 决策。router 只管一件事：这个任务是不是明显该全交给动态链。其余一切走 analyst。

#### Decision

**1. 路由职责：二选一起点指派**

router 不产出 `CapabilityTier`（那是 analyst 的职责），只产出 `RoutingDecision`：

```python
# src/common/contracts.py

class RoutingVerdict(str, Enum):
    DYNAMIC_ONLY = "dynamic_only"            # 明显开放：跳过整个静态链，直奔动态探索
    START_FROM_STATIC = "start_from_static"  # 其余一切：走完整静态链（含 analyst）
    # 注意：没有 STATIC_ONLY。router 不跳过 analyst——
    # "有本地数据"只影响 analyst 对 capability_tier 的判断，不改变 DAG 路径。

class RoutingDecision(BaseModel):
    verdict: RoutingVerdict
    reason: str = ""
    destinations: list[str] = Field(default_factory=list)
```

二选一逻辑：

```
router_node:
  ├── 明显开放（无结构化数据 + 查询意图明确需要多步探索）
  │     → RoutingVerdict.DYNAMIC_ONLY
  │     → 跳过 analyst/coder/auditor，直接走 dynamic_node → summarizer
  │
  └── 其余一切（含"有本地数据"的情况）
        → RoutingVerdict.START_FROM_STATIC
        → 走完整静态链（含 analyst）
        → analyst 在 ExecutionStrategy 中决定 capability_tier + fallback_tier
```

**router 如何判断"明显开放"**：不依赖少量领域关键词（如"经济走向"、"行业趋势"），而是组合三类信号：

| 信号类别 | 检测方式 | 示例 |
|---------|---------|------|
| 意图结构 | 查询中含探索性动词（研究、分析、调研、对比、评估）且无本地数据 | "帮我研究一下新能源汽车市场" |
| 时效性需求 | 查询含时间敏感词（最新、当前、最近、实时、今年）且无本地数据 | "最新的AI芯片进出口政策是什么" |
| 外部知识域 | 查询主题属于需要外部信息才能回答的领域（政策/法规/市场/行情/竞品/国际）且无本地数据 | "分析当前国际半导体供应链格局" |

三类信号都不命中 → `START_FROM_STATIC`。命中至少一类且无本地数据 → `DYNAMIC_ONLY`。命中但网络被禁 → 强制 `START_FROM_STATIC`。

**为什么不用少量硬编码关键词**：前版 `_DYNAMIC_SIGNALS` 只有 8 个词（"经济走向"、"行业趋势"等），`分析当前美国的经济走向` 曾被误判为 `need_more_inputs`，只能靠往列表里补词止血。改为意图结构 + 时效性 + 外部知识域三层信号后，覆盖面从"记住见过的 domain"变为"识别查询的结构特征"，不再依赖穷举领域词。

**2. CapabilityTier 一等枚举——analyst 填充，非 router 产出**

```python
# src/common/contracts.py

class CapabilityTier(str, Enum):
    STATIC_ONLY = "static_only"
    STATIC_WITH_NETWORK = "static_with_network"
    DYNAMIC_EXPLORATION_THEN_STATIC = "dynamic_exploration_then_static"
    DYNAMIC_ONLY = "dynamic_only"
```

四级语义：

| Tier | 含义 | 谁决定 |
|------|------|--------|
| `static_only` | 纯静态链，不联网 | analyst（分析后认为足够） |
| `static_with_network` | 静态链 + single-pass 外部取证 | analyst（分析后认为需要联网补充） |
| `dynamic_exploration_then_static` | 动态多步探索后回流静态链 | analyst（分析后认为单次取证不够，需多步探索） |
| `dynamic_only` | 纯动态，不回流产物交付 | router（明显开放）或 analyst（分析后认为不适合静态链） |

`CapabilityTier` 是 `ExecutionStrategy` 的字段（ADR-003），由 analyst LLM 填充。router 仅在极少数情况下（`DYNAMIC_ONLY`）决定跳过整个静态链，但此时也不写入 `CapabilityTier`——analyst 根本没被调用。

**3. 渐进式能力递进——analyst 的决策逻辑**

router 将"其余一切"交给 analyst 后，analyst 按渐进式判断：

```
1. 纯静态够不够？
   够 → capability_tier=static_only
   不够 ↓
2. 加一次联网能不能解决？
   能 → capability_tier=static_with_network
   不能 ↓
3. 需要多步探索吗？
   需要 → capability_tier=dynamic_exploration_then_static
   完全不值得 → capability_tier=dynamic_only
```

`fallback_tier` 声明当前 tier 失败时的降级目标（必须低于 capability_tier 的能力级别）。

**4. 派生字段不再独立存储——由 ExecutionStrategy 的 @computed_field 派生**

`analysis_mode`、`research_mode`、`strategy_family`、`generator_id`、`execution_intent` 全部从 `capability_tier` 单向派生，作为 `ExecutionStrategy` 的 `@computed_field`（详见 ADR-003 §1）。不再在 `ExecutionStrategy` 中独立存储这些字段。

```python
# 派生关系——单向，不可逆
def _derive_research_mode(tier: CapabilityTier) -> str:
    return {
        CapabilityTier.STATIC_ONLY: "none",
        CapabilityTier.STATIC_WITH_NETWORK: "single_pass",
        CapabilityTier.DYNAMIC_EXPLORATION_THEN_STATIC: "iterative",
        CapabilityTier.DYNAMIC_ONLY: "iterative",
    }[tier]

def _derive_execution_intent(tier: CapabilityTier) -> str:
    return {
        CapabilityTier.STATIC_ONLY: "static_flow",
        CapabilityTier.STATIC_WITH_NETWORK: "static_flow",
        CapabilityTier.DYNAMIC_EXPLORATION_THEN_STATIC: "dynamic_then_static_flow",
        CapabilityTier.DYNAMIC_ONLY: "dynamic_only",
    }[tier]
```

**5. 移除 fine routing 与 guidance 依赖**

`_maybe_refine_route_with_llm()` 在 pattern 粗分后做 LLM 精分路由。routing 简化为二选一粗筛后不再需要：

- **删除** `guidance_runner.py`（80行）——唯一调用方整体移除
- **删除** `guidance` 依赖（§1.4）
- **删除** `config/routing_policy.yaml` 中 `fine_routing` 配置段
- `resolve_runtime_decision()` 退化为纯粗分类，产出 `RoutingDecision`

**6. 旧字段兼容策略**

- `CapabilityTier` 枚举在 `ExecutionStrategy` 中新增，旧 checkpoint 无此字段 → 默认 `static_only`
- `analysis_mode`、`research_mode`、`strategy_family`、`generator_id` 在 `ExecutionStrategy` 中改为 `@computed_field`，旧 checkpoint 中存储的值被忽略（从 `capability_tier` 重新派生）
- `ResearchMode` Literal 类型保留不删（旧 checkpoint schema 仍引用）
- `single_pass_patterns` / `open_exploration_patterns` 保留但降级为 hint，不决定 tier

**7. routing_policy.yaml 降级**

pattern 列表保留但语义降级为"辅助粗筛判断的参考信号"，不再承担能力推断职责。router 的三层信号检测（意图结构 / 时效性 / 外部知识域）优先于 yaml 中的 pattern 列表。

#### Consequences

**变容易的事：**
- 要加新的路由行为只需加一个 `RoutingVerdict` 值 + router 里一个分支
- 线上排查路由问题直接看 `RoutingDecision.verdict`，不再翻 pattern 匹配日志
- `CapabilityTier` 由 analyst 统一决策（`DYNAMIC_ONLY` 除外——该路径跳过 analyst），不再被路由和 analyst 两个来源同时写入
- 渐进式能力递进由 analyst LLM 做出，不靠 pattern 关键词
- 后续 ADR-003 的 `ExecutionStrategy.capability_tier` 直接消费 `CapabilityTier`，analyst 成为 tier 的唯一决策者
- 三层信号检测（意图结构 / 时效性 / 外部知识域）替代少量硬编码关键词，不再需要为漏判往列表里补词

**变困难的事：**
- analyst LLM 需要理解渐进式判断（从 static_only 逐步升到 dynamic），对 prompt 设计要求更高
- 从 pattern 匹配迁移到 analyst 决策期间，可能出现 tier 判断不如旧 pattern 准确的回归
- 三层信号检测仍依赖规则，极端边缘 case 可能漏判（但漏判后果可控——走 analyst 而非直接错判路径）

#### Alternatives Considered

**A: Router 直接产出 CapabilityTier，analyst 只消费不决策。**
拒绝了——router 只有粗筛信息（有无本地数据、有无显式约束），无法做出 fine-grained 的能力判断。必须由 analyst 结合完整上下文决策。

**B: 保留 STATIC_ONLY 三选一，让 router 跳过 analyst。**
拒绝了——"跳过 analyst"意味着跳过 `ExecutionStrategy` 的唯一产出者。coder 拿什么生成代码？"有本地数据"不代表不需要分析（聚合方式、趋势方向、artifact 选择、联网判断）。router 的职责是粗筛起点，不是替代 analyst 的能力判断。

**C: 保留现状，等 AnalystPlan 上线后再统一。**
拒绝了——AnalystPlan 是 P2，但 routing 是 P1。先有显式梯度，AnalystPlan 才能声明自己需要哪个 tier。顺序不能反。

### ADR-003：ExecutionStrategy 单一真相源 —— 收口写入、消除双重存储、@computed_field 派生

**状态：** ACCEPTED
**日期：** 2026-04-30

#### Context

`ExecutionStrategy`（contracts.py:383）已经内嵌了 6 个子合同：`evidence_plan`、`artifact_plan`、`verification_plan`、`program_spec`、`repair_plan`、`resume_overlay`。模型层面不缺抽象，缺的是写入纪律和存储一致性。当前存在四个结构性问题：

1. **ExecutionStrategy 被 3 个节点先后覆写。** `analyst_node:192` 初始写入 → `coder_node:39` 覆写（registry 编译出 strategy_family、artifact_plan、verification_plan、program_spec）→ `debugger_node:79` 再次覆写（修复时重新编译）。规划语义从 analyst 产出后被 coder 和 debugger 改写，无法追溯"到底谁决定了什么"。

2. **四个子计划双重存储（5 个位置）。** `program_spec`、`repair_plan`、`artifact_plan`、`verification_plan` 既内嵌在 `ExecutionStrategy` 内部，又作为独立顶级 key 存在于 `ExecutionStaticState`（schema.py:704-709）、`NodeOutputPatchState`（schema.py:439-444）、`DagGraphState`（graphstate.py:66-71）。同一份数据存了 5 个位置，一致性靠 discipline 维护。

3. **规划输出是自然语言字符串。** `analysis_plan: str` 是一个 f-string 拼接的自由文本（analyst_node.py:122-137），同时存在 `exec_data.static.analysis_plan` 和 `exec_data.static.execution_strategy.legacy_compatibility["analysis_plan"]` 两处。DAG 无法据此做结构化决策。

4. **派生字段独立存储造成多源漂移。** `analysis_mode`、`research_mode`、`strategy_family`、`generator_id` 是 `capability_tier` 的派生值，却作为独立字段存储。这些字段可能被 Registry、coder、debugger 覆写，与 `capability_tier` 不一致。

目标：`ExecutionStrategy` 成为规划唯一真相源，analyst 为唯一写入者，借助 `frozen=True` + `@computed_field` 消除手动填充和双重存储。

#### Decision

**1. ExecutionStrategy 重构：frozen=True + @computed_field** ✅ 部分实现

> **已实现（2026-05-08）：** `frozen=True` 已加。`artifact_plan` / `verification_plan` 改为 `@computed_field`，从 `strategy_family` 派生（`_derive_artifact_plan()` / `_derive_verification_plan()`）。`_migrate_old_checkpoint` 剥离旧 checkpoint 中的这两个字段。
> **未实现：** `analysis_mode` / `research_mode` / `strategy_family` / `generator_id` / `execution_intent` 改为 `@computed_field` 从 `capability_tier` 派生（当前仍是独立字段）。`CapabilityTier` 4 值枚举未实现。`VerificationPlan.criteria` 未添加。

目标设计（TARGET）：

```python
# src/common/contracts.py

class ExecutionStrategy(BaseModel):
    model_config = ConfigDict(frozen=True)

    capability_tier: CapabilityTier = CapabilityTier.STATIC_ONLY
    fallback_tier: CapabilityTier | None = None
    summary: str = ""
    evidence_plan: EvidencePlan = Field(default_factory=EvidencePlan)
    artifact_plan: ArtifactPlan = Field(default_factory=ArtifactPlan)
    verification_plan: VerificationPlan = Field(default_factory=VerificationPlan)
    program_spec: StaticProgramSpec | None = None
    repair_plan: StaticRepairPlan | None = None
    resume_overlay: DynamicResumeOverlay | None = None
    legacy_compatibility: dict[str, Any] = Field(default_factory=dict)

    @computed_field
    @property
    def analysis_mode(self) -> str: ...

    @computed_field
    @property
    def research_mode(self) -> str: ...

    @computed_field
    @property
    def strategy_family(self) -> str: ...

    @computed_field
    @property
    def generator_id(self) -> str: ...

    @computed_field
    @property
    def execution_intent(self) -> str: ...
```

**2. 编译管道：Instructor → Pydantic（构造即冻结）**

```
analyst_node:
  输入：query + analysis_brief + knowledge_snapshot + business_context + approved_skills
    │
    ▼
  Instructor.from_openai(client).chat.completions.create(
      model="qwen-turbo",
      response_model=ExecutionStrategy,
      messages=[...],
  )
    │
    ├── 成功 → ExecutionStrategy(frozen=True) → 写入 blackboard + DagGraphState
    │
    └── 失败（3次重试耗尽，Instructor 内置 tenacity）
          → ExecutionStrategy(
                capability_tier=CapabilityTier.STATIC_ONLY,
                summary="Plan compilation failed, falling back to static analysis.",
            )
          → 写入 blackboard，任务继续
```

没有 Pass 3（Registry 手动填充）和 Pass 4（手动冻结）。Instructor 内置降级（`response_format` → `tool_choice`）和重试（tenacity, max 3次），项目侧不需要额外的降级/重试逻辑。

**3. 单一写入者：analyst_node**

```
analyst_node（唯一写入者）
    ↓ 产出 ExecutionStrategy(frozen=True)，写入 blackboard
    ↓ 写入 DagGraphState["execution_strategy"] = ExecutionStrategy 对象
    │
coder_node（只读消费）
    └── state["execution_strategy"] → build_codegen_prompt() → LLM 生成代码

debugger_node（只读 execution_strategy，修复走独立路径）
    └── 修复信息写入 DebugAttemptRecord + StaticRepairPlan

static_evidence_node（不碰 ExecutionStrategy）
    └── 写入 exec_data.static.evidence_bundle / exec_data.knowledge
```

各节点职责变更：

| 节点 | 现状 | 改后 |
|------|------|------|
| `analyst_node` | 写入初始 ExecutionStrategy + f-string analysis_plan | **唯一写入者**。Instructor LLM → `ExecutionStrategy(frozen=True)` |
| `coder_node` | 覆写 execution_strategy（:39） | **只读**。消费 ExecutionStrategy → `build_codegen_prompt()` → LLM → 代码 |
| `debugger_node` | 覆写 execution_strategy（:79） | **只读 execution_strategy**。修复信息走 `DebugAttemptRecord` + `StaticRepairPlan` |
| `static_evidence_node` | 写入 evidence 字段 | 写入 `evidence_bundle`，不碰 ExecutionStrategy |
| `static_generation_registry` | 覆写 strategy_family、program_spec 等 | **删除写入逻辑**。`strategy_family` 等改为 `@computed_field`，不再需要 registry 填充 |

**4. DagGraphState 简化：传 ExecutionStrategy 对象**

```python
# 旧：5 个独立 key，3 个 state 类重复存储
class DagGraphState(TypedDict):
    analysis_plan: str
    program_spec: dict
    repair_plan: dict
    artifact_plan: dict
    verification_plan: dict

# 新：一个 key，传冻结对象
class DagGraphState(TypedDict):
    execution_strategy: ExecutionStrategy  # frozen=True，只读传递
```

所有节点通过 `state["execution_strategy"]` 读取，字段路径从 `state["program_spec"]` → `state["execution_strategy"].program_spec`。

同步删除 `ExecutionStaticState`、`NodeOutputPatchState` 中的这 5 个顶级 key。

**5. 消除双重存储——删除清单**

| 操作 | 目标 | 位置 | 状态 |
|------|------|------|------|
| **删除** | `artifact_plan`（顶级 key） | `ExecutionStaticState`、`NodeOutputPatchState`、`PreparedStaticCodegen` | ✅ 已完成 |
| **删除** | `verification_plan`（顶级 key） | 同上 | ✅ 已完成 |
| **删除** | `ensure_artifact_plan()` / `ensure_verification_plan()` | `control_plane.py` | ✅ 已完成 |
| **删除** | `analysis_plan: str` | `ExecutionStaticState`、`NodeOutputPatchState`、`DagGraphState` | 未完成 |
| **删除** | `program_spec`（顶级 key） | `ExecutionStaticState`、`NodeOutputPatchState`、`DagGraphState` | 未完成 |
| **删除** | `repair_plan`（顶级 key） | 同上 | 未完成 |
| **删除** | `PreparedAnalysisPlan` dataclass | `analyst_node.py:22-27` | 未完成 |
| **删除** | `guidance_runner.py` | ADR-002 fine routing 移除后无用途 | 未完成 |
| **改为 @computed_field** | `analysis_mode`、`research_mode`、`strategy_family`、`generator_id` | `ExecutionStrategy` 内 | 未完成 |
| **改为 @computed_field** | `execution_intent`（原独立模型 `ExecutionIntent`） | `ExecutionStrategy` 内 | 未完成 |

**6. 旧字段兼容**

- `analysis_plan: str` → 删除。旧 checkpoint 读取时值迁移到 `ExecutionStrategy.legacy_compatibility["analysis_plan"]`。展示层读 `ExecutionStrategy.summary`（新）或 `legacy_compatibility["analysis_plan"]`（旧）。
- `analysis_mode`、`research_mode`、`strategy_family`、`generator_id` 旧存储值 → `@computed_field` 后从 `capability_tier` 重新派生，旧值忽略。旧字段在旧 checkpoint schema 中保留定义（标明 deprecated），但读取时走 computed。
- `program_spec`、`repair_plan`、`artifact_plan`、`verification_plan` 作为独立顶级 key → schema 定义保留但标记 deprecated。读取从 `ExecutionStrategy` 内部取；新 checkpoint 不写这些顶级 key。
- `PreparedAnalysisPlan` dataclass → 删除。analyst_node 直接构造 `ExecutionStrategy(frozen=True)`。

#### Consequences

**变容易的事：**
- 要理解一个任务"谁决定走哪条路" → 看 `ExecutionStrategy.capability_tier`（只有 analyst 写入，frozen 保证不被覆写）
- 要追溯规划变更 → git blame `analyst_node` 即可
- 派生字段（`strategy_family` 等）与 `capability_tier` 永远一致——`@computed_field` 保证
- 数据一致性由结构保证（一份数据，一个写入者，`frozen=True` 杜绝意外覆写）
- DagGraphState 只传一个对象，不再有字段不同步风险

**变困难的事：**
- analyst 依赖 Instructor + LLM 产出结构化 `ExecutionStrategy`，对 prompt 设计要求更高
- `frozen=True` 意味着任何时候修改 ExecutionStrategy 都需要重新构造（`model_copy(update={...})`），而不是属性赋值
- 旧 checkpoint 中 `analysis_plan: str` 不再有顶级字段，展示层需适配新路径

#### Alternatives Considered

**A: 新增 `AnalystPlan` 模型，与 `ExecutionStrategy` 分层。**
拒绝了——`ExecutionStrategy` 已经内嵌全部子合同，新增模型等于创建第 6 个存储位置。

**B: 保留双重存储，只加写入约束。**
拒绝了——只要顶级 key 存在，就会有代码直接读它，一致性无法靠 convention 保证。

**C: 保留 `analysis_plan: str` 降级为展示字段。**
拒绝了——`ExecutionStrategy.summary` 已承担展示角色。旧数据通过 `legacy_compatibility` 保留即可。

### ADR-004：static codegen 从模板驱动改为 LLM 驱动

**状态：** ACCEPTED / 未实现
**日期：** 2026-04-30

#### Context

当前 codegen 两条路径本质都是模板驱动：

- **Compiler 路径：** `build_static_program_spec()` 用写死的 if-else 生成 `ComputationStep` 列表 → `compile_static_program()` 把 spec + payload 塞进 `_COMPILER_TEMPLATE` 字符串替换
- **Legacy 路径：** `render_dataset_aware_code()` 模板渲染 → `_inject_artifact_writer()` 字符串注入

审计原话：*"即使 codegen 逻辑变灵活，输出语义仍被固定 family 封顶。"*

lite-interpreter 的本质是"可控的 LLM 分析"。让 LLM 在约束下生成任务自适应代码，由 auditor 验证、debugger 修复——这正是项目已有的控制链路。模板反而是这个链路里多余的限制层。

#### Decision

**1. 统一 codegen 路径：coder_node 直接调 LLM → auditor 验证**

coder_node 不再覆写 `ExecutionStrategy`，也不依赖 registry 模板编译。它直接消费 analyst 产出的冻结 `ExecutionStrategy`，按其中的约束合同调 LLM 生成代码：

```
旧（两条模板路径）:
  registry → strategy_family
    ├── compiler 路径 → compile_static_program() → 模板渲染
    └── legacy 路径 → render_dataset_aware_code() + 字符串注入

新（一条 LLM 路径）:
  analyst_node → ExecutionStrategy(frozen) → DagGraphState
    │
    ▼
  coder_node
    ├── state["execution_strategy"] → 读取约束合同
    ├── build_codegen_prompt(spec, skills) → litellm LLM → Python code
    └── auditor 验证（Tree-sitter AST + artifact contract + sandbox policy）
        ├── 通过 → sandbox 执行
        └── 失败 → debugger repair / fallback
```

`code_compiler.py` 不是 DAG 节点，是 `coder_node` 内部调用的纯函数模块（§1.6）。

**2. ExecutionStrategy + StaticProgramSpec 作为 LLM 约束合同**

coder_node 直接读取 `state["execution_strategy"]`（冻结的 `ExecutionStrategy` 对象），`StaticProgramSpec` 和 `ArtifactPlan` 作为 prompt 约束：

```python
def build_codegen_prompt(
    execution_strategy: ExecutionStrategy,
    skills: list[CodegenSkill],
    payload: dict,
) -> str:
    """从 ExecutionStrategy 构建 LLM codegen 的约束 prompt。"""
    spec = execution_strategy.program_spec
    plan = execution_strategy.artifact_plan
    return f"""
You are generating Python code for a sandboxed analysis task.

## Constraints (MUST satisfy)
- Required computation steps: {[s.kind for s in spec.steps]}
- Required artifacts: {[a.file_name for a in spec.artifact_emits if a.required]}
- Prohibited extensions: {execution_strategy.verification_plan.prohibited_extensions}
- Output root: {plan.output_root}
- Sandbox policy: no network, no disallowed modules, max code length enforced by governor

## Reference skills (for style and pattern, not mandatory)
{format_skills(skills)}

## Available data
{summarize_payload(payload)}

Generate self-contained Python code that satisfies ALL constraints.
"""
```

**3. 预定义 skills 作为参考，不是模板**

skills 是 few-shot 参考，LLM 可以参考但不被限制：

```
skills/
  codegen/
    dataset_profile.py      ← "这是一个 dataset_profile 分析的参考实现"
    document_rule_audit.py  ← "这是一个 rule_audit 的参考实现"
    hybrid_reconciliation.py
    input_gap_report.py
```

这些 skill 文件是可运行的参考代码，LLM 根据任务特征选择性地参考它们的模式，但不做字符串替换。新增 strategy 时只需加新的 skill 文件，不改 registry。

**4. 旧代码的去向**

| 旧组件 | 去向 |
|--------|------|
| `compile_static_program()` | 删除。不再需要模板编译 |
| `_COMPILER_TEMPLATE` | 内容提取为 skill 文件 `skills/codegen/` |
| `render_dataset_aware_code()` | 退化为 legacy adapter，只在旧 checkpoint replay 时用 |
| `_inject_artifact_writer()` | 删除。artifact writer 逻辑写进 LLM prompt 约束，不再字符串注入 |
| `_artifact_writer_snippet()` | 逻辑提取到 `skills/codegen/_artifact_utils.py`，作为 LLM 可参考的工具函数 |
| `build_static_program_spec()` | 保留，但职责从"生成模板输入"变为"生成 LLM 约束合同" |

**5. Auditor 增强：Tree-sitter 替代 stdlib ast**

当前 `ast_auditor.py` 使用 Python 标准库 `ast` 做安全审计，仅检查 import / builtins / method call 的字符串黑名单，无法检测语法结构级别的风险（如 `eval("ev"+"al")` 拼接绕过），无法标注具体行号和严重级别。

改用 **Tree-sitter** + `tree-sitter-python`：

- **语法结构模式匹配**：通过 Tree-sitter query language 做结构化匹配（如"检测所有 `eval()` 调用，但不包括 `eval` 赋值给变量的情况"），替代字符串黑名单
- **精确到行号的标注**：每个风险点标注 `{line, column, severity, rule_id}`，不再整段通过/拒绝
- **可扩展的规则集**：新增审计规则只需加 query 模板，不改 auditor 逻辑

```python
# Tree-sitter 审计示例
query = language.query("""
    (call
      function: (identifier) @func_name
      arguments: (argument_list) @args
    )
""")
matches = query.captures(tree.root_node)
```

`ast_auditor.py` 整体重写为 `src/compiler/code_auditor.py`（§1.4 依赖调整中引入 tree-sitter 替代 stdlib ast）。

LLM 驱动后需要额外校验：

| 校验层 | 含义 | 现存？ |
|--------|------|--------|
| AST safety audit | 代码不含危险调用（Tree-sitter query 模式匹配） | 重写为 `src/compiler/code_auditor.py` |
| Sandbox policy | governor deny_patterns + code length | 已有 |
| Artifact contract | 产物文件是否与 `ArtifactPlan` 一致 | 已有 `verify_generated_artifacts()` |
| **新增：Execution compliance** | 生成的代码是否实际执行了 spec 中声明的 computation steps | 新增 |
| **新增：Output quality** | 产物内容是否合理（非空、格式正确、引用了数据源） | 新增 |

auditor 失败 → debugger 生成 `RepairDecision` → 重试（最多 2 次）→ 仍失败 → `fallback_to_legacy`。

**6. Migration**

- Phase 4a: 新增 `CodegenSkill` 模型 + `build_codegen_prompt()` + skills 目录
- Phase 4b: 新增 LLM codegen 路径，与 compiler 路径并跑（`strategy_family != legacy` 时走新路径）
- Phase 4c: auditor 增强（execution compliance + output quality）
- Phase 4d: compiler 模板删除，legacy renderer 降级为 replay-only adapter

#### Consequences

**变容易的事：**
- 加新 artifact 类型：改 `ArtifactPlan` + 加 skill 文件，不改编译器和模板
- 改代码风格：改 skill 文件或 prompt，不改代码逻辑
- 任务自适应：LLM 根据实际数据特征生成针对性代码，不再受固定 template 封顶
- 回滚：`fallback_to_legacy` 仍然可用

**变困难的事：**
- LLM 生成的代码可能不可靠——依赖 auditor + debugger 作为安全网
- Prompt 工程成为新的关注点：`build_codegen_prompt()` 的质量直接影响代码质量
- 旧 checkpoint replay：LLM 重新生成代码可能与原始结果不同（可接受——结果相似即可）

#### Alternatives Considered

**A: 保留模板驱动，只合并两条路径为一条。**
拒绝了——合并后仍是模板，审计说的"被框架封顶"问题没有解决。且 lite-interpreter 的目标就是可控 LLM 分析，模板是多余的中间层。

**B: 完全删除模板，纯 LLM 生成，无 reference。**
拒绝了——没有 skill 参考，LLM 生成质量方差太大。预定义 skill 作为 few-shot 参考是低成本的质量锚。
