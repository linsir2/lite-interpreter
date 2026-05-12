# SDD: lite-interpreter v2 架构设计文档

状态：IN PROGRESS（部分实现）
日期：2026-04-29
最后更新：2026-05-09

## 实现进度（2026-05-09）

| ADR | 状态 | 已完成 | 待完成 |
|-----|------|--------|--------|
| ADR-001 | 进行中 | DeerFlow 删除 + 原生 LLM tool-calling loop 替换 |
| ADR-002 | ✅ 已删除 | router 退化为二进制粗筛，CapabilityTier 4 值枚举，详情见 git 历史 |
| ADR-003 | ✅ 已删除 | ExecutionStrategy frozen=True，@computed_field 派生，单一写入者，详情见 git 历史 |
| ADR-004 | ✅ 已删除 | LLM codegen 主路径 + 模板 fallback，详情见 git 历史 |
| ADR-005 | 草案 | 2026-05-10 Stress Test 完成：4 道题拷打 DAG，识别 3 个拓扑缺陷 + 6 个契约缺口。CapabilityTier 决策为正交 2 维度 |

> **已完成 ADR（002/003/004）的正文已从本文档删除，实现细节见 git log。**

## 1. 设计目标与约束

### 1.1 问题陈述

lite-interpreter 有一条真实存在的主骨架（Web 前端 → `/api/app/*` 合同 → Blackboard 状态事实源 → DAG 编排 → Sandbox 执行边界），但当前被四组系统性张力持续削弱：

1. **DeerFlow 仍是外部运行时依赖，动态能力不归自己。** `dynamic_swarm_node` 本质上是对 DeerFlow sidecar HTTP streaming 的适配层，supervisor / bridge / trace_normalizer 都围绕这个外部边界设计。动态路径不是 lite-interpreter 自己的原生探索循环。
2. **路由缺乏显式能力梯度合同，且职责过重。** 当前 routing 依赖 pattern 匹配承担了"选起点"和"定路径"双重职责，而真正的能力级别判断应该由 analyst 做出。routing 应退化为粗筛——只决定起点（明显简单 / 明显开放 / 其余从静态开始），不决定后续的能力升级。
3. **`ExecutionStrategy` 不是规划权威——多主写入 + 自然语言字符串 + 双重存储。** `analyst` 产出自然语言 `analysis_plan: str`（f-string 拼接），DAG 行为仍由 preset + registry 决定。`ExecutionStrategy` 虽内嵌了 `evidence_plan`、`artifact_plan`、`verification_plan`、`program_spec`、`repair_plan`，但被 `analyst` → `coder` → `debugger` 三个节点先后覆写，coder 兼任 planner / compiler / contract builder，子计划同时作为顶级 key 重复存储在 3 个 state 类中（5 个位置存同一份数据）。同时 `analysis_mode`、`research_mode`、`strategy_family`、`generator_id` 等字段是 `capability_tier` 的派生值，不应独立存储。
4. **产物交付面被固定 family 限死。** artifact family 与 emit kind 被 registry 固定，用户看不到任务特化的完整交付物。

### 1.2 v1 范围与优先级

按 DAG 自底向上顺序解决——先让下游节点自立，再让上游获得权威：

| 优先级 | 问题 | 理由 |
|--------|------|------|
| P0 | DeerFlow 内化为 `dynamic_exploration_node` | analyst 的下游节点不归自己，analyst 就无法成为真权威 |
| P1 | 路由能力梯度合同一等化 | 入口必须先有显式梯度，后续节点才能按合同分流 |
| P2 | `ExecutionStrategy` 单一真相源 | 补齐字段、消除双重存储、analyst 成为唯一写入者，禁止 coder/debugger 覆写 |
| v2 | 产物交付面任务特化 | 报告/图表/表格/诊断产物/来源引用/对账轨迹 |

### 1.3 NON-goals（v1 明确不做）

- 删除所有 DeerFlow 代码和依赖（不保留 fallback）
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
- DeerFlow 依赖已整体删除（ADR-001 实现时一步到位）
- 净依赖变化：+2 (instructor, tree-sitter) -1 (guidance) -1 (deerflow 日后) = 持平或更少

### 1.5 硬约束

- **旧 checkpoint 必须可读。** 任何 Pydantic schema 变更必须向后兼容。旧数据优先读新字段，缺失时 adapter 补。
- **旧字段不直接删除，走 migration window。** `analysis_plan` → 最晚删（挂展示层），`generation_directives` → registry 稳定后删，`next_static_steps` / `dynamic_next_static_steps` → 一起退。
- **迁移原则：先加新字段双写，再旧字段降级为 compatibility，最后删旧。**
- **`legacy_dataset_aware_generator` 从 Literal 删除后，旧 checkpoint 通过 migration validator 读旧数据时自动映射为 `dataset_profile`。** 迁移逻辑写入 `StaticProgramSpec`、`GeneratorManifest`、`DynamicResumeOverlay`、`ArtifactVerificationResult` 的 `model_validator(mode="before")`。
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


### ADR-001：DeerFlow 删除 + 原生 LLM 工具调用循环

**状态：** ACCEPTED / 实现中
**日期：** 2026-04-30（上次更新 2026-05-09）

#### Context

当前动态路径的唯一实现是 `dynamic_swarm_node` → `DeerflowBridge` → DeerFlow sidecar HTTP streaming。DeerFlow 是一个 ByteDance 开源的 SuperAgent Harness 框架，提供子代理编排、Plan-Execute-Reflect 循环、11 层中间件链等能力。但它引入了不必要的复杂度：

- 动态探索能力不归 lite-interpreter 自己所有
- HTTP sidecar 带来进程边界、事件归一化开销、调试困难
- DeerFlow 的工具/沙箱/技能/前端能力与 lite-interpreter 已有的实现重叠

目标：**直接删除 DeerFlow 代码和依赖，用原生 LLM tool-calling loop 替代。** 不保留 fallback。

#### Decision

**1. 删除清单**

| 删除项 | 说明 |
|--------|------|
| `src/dynamic_engine/deerflow_bridge.py` | HTTP sidecar 桥接层 (413 行) |
| `src/dynamic_engine/supervisor.py` | 旧 DynamicSupervisor (225 行) |
| `src/dynamic_engine/blackboard_context.py` | DeerFlow 上下文信封 (122 行) |
| `src/dynamic_engine/runtime_backends.py` | 运行时能力清单 (171 行) |
| `src/dag_engine/nodes/dynamic_swarm_node.py` | 旧 DAG 节点 (215 行) |
| `scripts/run_deerflow_sidecar.py` | Sidecar 启动脚本 |
| `scripts/smoke_deerflow_bridge.py` | 冒烟测试 |
| `config/deerflow_sidecar.yaml` | Sidecar 配置 |
| `tests/test_deerflow_bridge.py` | Bridge 测试 |
| `tests/test_deerflow_sidecar.py` | Sidecar 测试 |
| `deerflow-harness` pip 包 | 卸载 |

**2. 原生探索循环（`src/dynamic_engine/exploration_loop.py`）**

核心是 OpenAI function-calling 格式的 LLM 工具调用循环。每轮一步，记录完整轨迹：

```python
class ExplorationStep(BaseModel):
    """探索循环中单步的轻量记录，供后续 skill 固化。"""
    step_index: int
    tool_name: str
    tool_args: dict[str, Any]
    tool_result_summary: str  # 截断后的工具返回摘要
    rationale: str            # LLM 为什么选这个工具
    observation: str          # LLM 从结果中学到了什么
    decision: str             # LLM 决定下一步做什么
    success: bool
    error: str | None = None
```

循环逻辑：

```
run_exploration_loop(query, context, allowed_tools, max_steps=6, on_event=None):
  1. 从 MCP gateway 加载可用工具的 OpenAI function-calling schema
  2. 构建 system prompt（含工具说明、边界约束、沙箱使用规则）
  3. 每轮循环：
     a. LLM 接收当前 messages（含历史工具调用）
     b. LLM 决定：调用一个工具 OR 输出最终答案
     c. 如调用工具 → 执行 → 记录 ExplorationStep → 追加到 messages
     d. 如最终答案 → 解析 summary/open_questions/next_steps → 返回
     e. 步数耗尽 → 强制 summarize 已有发现
  4. 返回 ExplorationResult（含 ExplorationStep[]）
```

**3. 探索完成条件**

探索在以下情况结束：
- LLM 主动输出最终答案（包含 ### Summary 节）
- 步数预算耗尽（max_steps 硬限制）
- 工具反复失败且无替代路径（记录 error 到最终 summary）

**4. 沙箱使用约束**

循环内的 `sandbox_exec` 仅用于临时轻量计算（验证假设、小规模聚合、数据转换）。系统 prompt 明确约束：

> sandbox_exec is for lightweight temporary computation only. Heavy analysis that produces user deliverables MUST be deferred to the static chain (coder → executor). Do NOT write final report-generation code here.

**5. 回写路径**

探索循环不直接读写 blackboard。`dynamic_node()` 消费 `ExplorationResult`，通过现有 `ExecutionStateService.update_dynamic()` 回写：

```
ExplorationResult.to_state_patch() → DynamicResumeOverlay → ExecutionDynamicState
```

`DynamicResumeOverlay` 字段复用现有 contract，无 schema 变更。仅 `runtime_backend` 值从 `"deerflow"` 变为 `"native"`。

**6. 联网工具**

`web_search`、`web_fetch` 是探索循环内的一等 MCP 工具，可多步迭代调用（搜 → 读 → 再搜 → 再读），与静态链路的单次取证完全不同。

**7. 编译层约束**

探索循环 prompt 由编译层 `build_codegen_prompt()` 风格构建（字段约束 + 工具清单 + 边界声明），LLM 中间决策受 prompt 约束。最终产出 `DynamicResumeOverlay` 走 `ensure_dynamic_resume_overlay()` 验证。

#### Consequences

**变容易的事：**
- 动态探索能力完全在进程内，无网络/进程依赖
- 工具调用由 MCP 网关统一管理，不维护两套工具配置
- 轨迹记录（ExplorationStep）结构化，可固化为 skill
- 删除约 1500 行 DeerFlow 胶水代码
- 净依赖变化：-1 (deerflow 删除)

**变困难的事：**
- 探索循环质量依赖 prompt 工程（需迭代优化）
- ExplorationStep 需要为 skill 固化场景设计合适的粒度
- 旧 checkpoint 中 `runtime_backend="deerflow"` 需 migration 处理

#### Alternatives Considered

**A: 保留 DeerFlow 作为 fallback（原始 SDD v2 设计）。**
拒绝了——用户要求彻底删除。且两套 backend 并存增加维护负担，NativeExplorationBackend 已经够用。

**B: 保留 DeerFlow 的探索循环代码（子代理、中间件），只删沙箱/前端。**
拒绝了——增加复杂度，DeerFlow 的核心价值（多步探索）可以用 ~300 行原生代码实现。


### ADR-005：多步静态链 + 联网一等节点 + 渐进式 Skill 检索

**状态：** DRAFT / 未实现
**日期：** 2026-05-09（上次更新 2026-05-10）

#### Stress Test：4 道题拷打 DAG

在确定方案前，用 4 道真实业务问题对当前 DAG 做了压力测试，覆盖从简单到最高复杂度的场景。同时从 DAG 拓扑和数据流/契约两个角度交叉分析。

**4 道题及判决：**

| 题 | 复杂度 | 核心特征 | 当前 DAG |
|----|--------|---------|---------|
| 1. FIFO 逐票核销 | 低 | 单次静态链，核销→逾期硬拓扑依赖 | ✅ 能跑 |
| 2. AR 周转恶化归因 | 中 | 5 轮本地分析迭代，每轮方向由上一轮发现决定 | ❌ 跑不通 |
| 3. 跨境关税冲击评估 | 中高 | 本地数据+外部迭代搜索，"税率查找表"填满即停 | ❌ 跑不通 |
| 4. Q1 收入异常归因与跨源对账 | 高 | 本地分析→外部搜索→跨源对账→报告，static↔dynamic 交替 | ❌ 跑不通 |

详细题目见 [stress-test-cases](./stress-test-cases.md)（待补充）。

**题 1（FIFO 核销）能跑的原因：** 单次静态链内顺序执行即可。FIFO 核销逻辑和逾期计算的依赖关系在 coder 生成的 Python 代码内部处理，不需要 DAG 节点间反馈弧。

**题 2-4 跑不通的三个独立根因，都不是"某个节点不够聪明"：**

1. **缺少 static→static 多轮迭代回路**（题 2）：当前静态链 `analyst→coder→executor` 只执行一次。5 轮归因分析（趋势扫描→贡献度拆解→候选客户深潜→一次性因素剥离→归因合成）只跑第一轮就结束。当前唯一的回路是 `auditor→debugger→executor` 的修复回路，不是分析性多轮迭代。

2. **Router 的"有本地数据=不需要动态探索"假设是错的**（题 3）：题目有 export_transactions CSV 等本地数据，router 判 `static_flow`。但题目需要 4 轮迭代搜索（锚定权威源→补搜豁免→澄清累加规则→兜底验证），这个能力只存在于 `dynamic_node` 的 exploration loop 里。Analyst 即使设了 `capability_tier=DYNAMIC_EXPLORATION_THEN_STATIC`，拓扑已定，改不了——**analyst 的 capability_tier 是装饰性的。**

3. **静态和动态被建模为互斥路径，不能交替**（题 4）：最优链路是 `本地拆解(static) → 外部搜索(dynamic, 搜索目标由拆解结果决定) → 跨源对账(static) → 报告`。当前 DAG 只有"纯静态"或"先动态后静态单向"两条路，不存在 static→dynamic→static 的交替。

#### 从 Stress Test 得出的设计决策

**决策 1：CapabilityTier 拆为正交维度，而非单枚举**

不管 2 值还是 4 值，关键维度都没被表达——当前 tier 表达的是"要不要联网"，但真实缺失的维度是"要不要多轮"和"联网的类型"。

| 题 | iteration 需求 | network 需求 |
|----|---------------|-------------|
| 1 FIFO | single_pass | none |
| 2 AR 归因 | multi_round | none |
| 3 关税 | multi_round | bounded（结构化填表，有明确终止条件） |
| 4 收入归因 | multi_round | open（搜索目标由中间结果决定） |

**方案：** ExecutionStrategy 增加两个正交字段，替代单一 CapabilityTier 枚举：

```python
class NetworkMode(str, Enum):
    NONE = "none"           # 不需要联网
    BOUNDED = "bounded"     # 结构化查询：analyst 指定查询集，迭代填表，终止条件明确
    OPEN = "open"           # 开放探索：LLM 自主决定搜什么、去哪搜、何时停（走 dynamic_node）

class IterationMode(str, Enum):
    SINGLE_PASS = "single_pass"   # 单次静态链
    MULTI_ROUND = "multi_round"   # 多轮静态链（analyst 每轮决定是否继续）
```

原 `CapabilityTier` 枚举（STATIC_ONLY / STATIC_WITH_NETWORK / DYNAMIC_EXPLORATION_THEN_STATIC / DYNAMIC_ONLY）在 migration window 期间保留为向后兼容字段，降级为 analyst 的"推荐策略 hint"，不被 DAG 做硬决策。

`Router` 的路由逻辑从"看 capability_tier"改为看 `network_mode`：`OPEN → dynamic_flow`，`NONE` 或 `BOUNDED → static_flow`。

**决策 2：联网的三种形态，三种 DAG 位置**

| 联网类型 | 谁来驱动 | DAG 位置 | 例子 |
|---------|---------|---------|------|
| **开放探索型** | LLM 自主循环，边搜边决定下一步 | 独立节点 `dynamic_node`（renamed `exploration_node`） | 题 3 的"找最新 301 关税清单"、题 4 的"用拆解结果驱动外部搜索" |
| **结构化查询型** | Analyst 指定查询集和域，节点迭代直到数据完整 | 升级 `static_evidence` 支持 `research_mode="iterative"` | 题 3 的"填满 HS 84/85/94 的税率查找表" |
| **辅助型** | 节点中途临时查一个事实 | 节点内嵌 MCP 工具调用，受 governance 约束 | coder 写代码时需要确认某 API 的调用方式 |

**关键区分：能不能提前写出搜索计划。** 如果 analyst 能写出完整的 `EvidencePlan`（哪怕分多轮执行），走结构化查询型。如果"连该搜什么词都不知道，需要根据中间结果动态调整"，走开放探索型。

**决策 3：静态链多轮迭代回路**

在 `_execute_static_flow()` 内加 `while` 循环，`analyst→coder→executor` 可多轮执行：

```python
def _execute_static_flow(state, next_actions, nodes, max_rounds=3):
    for round_idx in range(max_rounds):
        result = _execute_single_pass(state, next_actions, nodes)
        # Analyst 在每轮结束时判断是否继续
        if not result.get("additional_rounds", 0):
            return result
        next_actions = result.get("next_static_steps") or ["analyst"]
```

**终止条件由 analyst 判断**（不需要独立的 loop_controller）：
- Analyst 产出 `additional_rounds = 0` → 停止，进入 summarizer
- `additional_rounds > 0` → 继续下一轮，analyst 重新分析（带上一轮的 `RoundOutput`）
- 安全阀：`MAX_STATIC_ROUNDS` 硬上限（默认 3）

Analyst 的判断依据：上一轮发现了什么、是否需要深挖、是否需要联网——这些都是 analyst 的职责。

**决策 4：static↔dynamic 交替能力**

在动态链回流到静态链后，静态链的多轮循环中 analyst 可以再次触发动态探索：

```
dynamic_node→analyst→coder→executor→analyst(设 network_mode=OPEN)→dynamic_node→analyst→...
```

实现上不是新拓扑，而是把 dynamic_node 作为静态链的"可调用节点"——analyst 的 `next_static_steps` 可以包含 `"dynamic"`，触发新一轮动态探索。治理侧需要对交替次数设上限（`MAX_DYNAMIC_ROUNDS`，默认 2）。

**决策 5：渐近式 Skill 检索**

替换 `MemoryService.recall_skills()` 的一次性全量检索：

- 第一轮：检索基础分析 skill（`stage="analyst"`, `top_k=3`）
- 第 N 轮：`recall_skills()` 接受 `prior_findings` 参数（上一轮的 `RoundOutput.key_findings` 语义摘要），做增量语义匹配
- Skill 的选择不再绑定在静态链开头，而是分发到每轮 analyst 调用时

#### 契约缺口（本次实现范围待定）

Stress test 暴露了 6 个数据流/契约缺口，按严重程度排序：

| 优先级 | 缺口 | 说明 | 影响 |
|--------|------|------|------|
| **P0** | `RoundOutput` | executor→analyst 的轮间输出语义传递。当前只有文件路径（`ArtifactRecord.path`），没有结构化结论摘要 | 题1,2,4：analyst 不知道上一轮算出了什么 |
| **P0** | `ExternalKnowledge` | 结构化外部知识（税率查找表、竞品数据）。当前 `DynamicResumeOverlay.evidence_refs` 只有裸 URL，`dynamic_research_findings` 是裸字符串列表 | 题3,4：外部信息无法被 coder 消费（coder 需要 schema，不是自然语言） |
| **P0** | 静态链多轮循环控制 | `_execute_static_flow` 单遍执行，无 `additional_rounds` 信号 | 题2,4：多轮分析无法触发 |
| P1 | 多轮 `ExecutionStrategy` 版本链 | 当前只有单槽位 `execution_strategy`。多轮需支持每轮独立 frozen strategy，旧版归档到 journal | 题2,4：无法追溯每轮的计划演变 |
| P1 | `EvidenceLineage` | 每条结论→数据源→外部知识条目→计算步骤的可追溯链 | 题3,4：报告中的结论无法验证来源 |
| P1 | 搜索计划由中间结果驱动 | 当前 `EvidencePlan` 是 analyst 一次性声明。多轮需要 analyst 读中间结果后写 `EvidencePlan` v2 | 题4：阶段2的拆解决定了阶段3的搜索目标 |

`frozen=True` + analyst 唯一写入者的约束**不需要改变**——每轮 analyst 产出新的独立 frozen strategy，不修改旧的。

#### Consequences

**变容易的事：**
- 2 维度（network_mode + iteration_mode）比 4 值枚举覆盖了更多真实组合
- 三种联网形态的 DAG 位置各司其职，不再混在一个节点
- Analyst 成为多轮循环的终止决策者（不是被动执行者），角色不弱反强
- 渐进式 skill 检索使每轮都有针对性的知识复用

**变困难的事：**
- 静态链多轮循环的 while 逻辑需要在不引入新编排框架的前提下实现
- static↔dynamic 交替的治理约束（次数上限、防止死循环）
- RoundOutput 和 ExternalKnowledge 的 schema 设计需要在 producer/consumer 之间找到合适的抽象层次
- 旧 checkpoint 中 `CapabilityTier` 4 值到新 2 维度的 migration

#### Open Questions

- `network_mode: bounded` 和 `network_mode: open` 的边界是否总是清晰的？题 3 的关税搜索在"税率不确定"时可能从 bounded 滑向 open
- `additional_rounds` 由 analyst 声明还是由 executor 执行后自动进入下一轮让 analyst 判断？如果 analyst 声明了 `additional_rounds=2` 但第一轮就得到了满意结果，能否提前终止？
- 多轮之间的 knowledge snapshot 是否需要增量更新（每轮 executor 产出追加到 snapshot），还是全量重建？
- `RoundOutput` 的粒度：是 executor 级别的（一轮一个），还是更细的（一轮多个发现）？
- `ExternalKnowledge` 的 schema：tagged union（LookupTable | NumericFact | TextualFinding | DocumentSummary）够不够？
- 静态链多轮联网（bounded + iterative）的 `static_evidence` 升级是否应在 ADR-005 范围内，还是单独的 ADR？


