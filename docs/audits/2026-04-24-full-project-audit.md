# lite-interpreter 项目完整审计报告

日期：2026-04-24

## 审计范围

本次审计覆盖以下层面：

- 项目整体架构与边界设计
- DAG / 静态链 / 动态链 的流水线流转
- 代码生成与产物交付模型
- 信任边界与治理执行面
- 依赖、配置、部署与运行姿态
- 测试、文档与发布就绪度信号

这是一份面向整个仓库的工程审计报告，不只是一次代码差异审查。

## 审计方法

本次审计使用的 skills 与审查视角：

- `project-audit`
- `code-review-and-quality`
- `security-review`
- `documentation-and-adrs`

补充审查方式：

- 多轮 `crs + gpt-5.5` 交叉审查，分别覆盖：
  - 架构与流水线设计问题
  - 项目级依赖 / 配置 / 发布就绪度问题

## 验证证据

本轮审计期间实际执行的本地验证：

- `conda run -n lite_interpreter python -m ruff check src tests scripts config`
  - 结果：通过
- `conda run -n lite_interpreter python -m pytest -q`
  - 结果：`260 passed, 4 skipped`

本轮未直接审计的内容：

- 浏览器端实时交互走查
- 真实生产部署环境
- 基于在线漏洞数据库的外部依赖 CVE 实时扫描

## 执行摘要

这个项目已经形成了一条比较明确的主骨架：

- Web 前端
- `/api/app/*` 应用侧合同
- Blackboard 作为状态事实源
- DAG 作为编排主控
- Sandbox 作为最终执行边界

这条骨架是真实存在的，但当前仍被四组系统性张力持续削弱：

1. 规划器（`analyst`）还不是一个真正可执行的规划权威
2. 静态代码生成路径仍然本质上是模板驱动的
3. 动态研究仍然以 DeerFlow sidecar 依赖的方式存在，而不是 lite-interpreter 自己的 DAG 原生能力
4. 项目级工程真相仍然分散在依赖、配置、文档和验证面之中

因此，这个项目现在更像是一个架构正在快速收口的工程化原型，而不是一个已经达到生产级稳定性的分析平台。当前最关键的问题不是单点 bug，而是边界、所有权和真相源问题。

## 主要发现

### 一、高优先级问题

#### 1. `analyst` / 静态生成链仍缺少可执行规划控制权

严重级别：HIGH

合并范围：

- 原问题 2：静态代码生成仍然是模板驱动，不是真正按任务生成代码
- 原问题 3：产物交付面仍被固定 family 和固定 emit 限死
- 原问题 29：DAG 仍是硬编码流程脚本，不是 plan-driven DAG
- 原问题 32：`ExecutionStrategy` 名义上是真相源，实际上 owner 被拆散
- 原问题 33：Coder 不是清晰的代码生成边界，而是一次性写入 strategy/spec/artifact/verification 多个合同
- 原问题 43：static codegen 存在“双后端 + 模板注入”架构债务，输出语义分散

证据：

- `src/dag_engine/nodes/analyst_node.py:122`
- `src/dag_engine/nodes/analyst_node.py:180`
- `src/dag_engine/dag_graph.py`
- `src/dag_engine/nodes/coder_node.py:34`
- `src/dag_engine/nodes/static_codegen.py:37`
- `src/dag_engine/nodes/static_codegen_payload.py`
- `src/dag_engine/nodes/static_generation_registry.py`
- `src/dag_engine/nodes/static_program_compiler.py`
- `src/dag_engine/nodes/static_codegen_renderer.py`
- `src/dag_engine/nodes/debugger_node.py`

问题说明：

- `analyst` 当前主要产出的是自然语言形式的 `analysis_plan`
- DAG 真正执行的静态链结构仍然是硬编码的
- `coder` 之所以在 `analyst` 之后执行，核心原因仍然是图上写死了顺序，而不是 `analyst` 产出了一个任务特化的执行计划
- 真正的控制对象虽然已经开始向 `execution_strategy` 收敛，但它仍然主要由既有策略 helper / registry / coder / debugger 分段填充，而不是由 `analyst` 产出高表达力的计划合同后驱动整个 DAG
- `static_codegen_payload` 会派生 hints、terms、focus order，但这些仍是 payload enrichment，不是可执行规划合同
- registry 仍能基于输入数量、业务信号、existing payload 推导 `strategy_family`、artifact plan 与 verification plan
- `coder_node` 调用 `prepare_static_codegen()` 后，同时写入 generated code、execution strategy、program spec、artifact plan、verification plan、repair plan 与 manifest，导致 coder 兼任 planner/compiler/contract builder
- 非 legacy 路径走 `StaticProgramSpec -> compile_static_program()`，legacy 路径走 `render_dataset_aware_code()` 再用字符串替换注入 artifact writer，输出语义分散在 registry、compiler、renderer 三处
- artifact family 与 emit kind 被 registry 固定，无法由任务级 plan 声明更丰富的交付物

为什么重要：

- 系统表面上看起来“有规划”，但规划实际上没有被授予足够控制权
- DAG 行为仍然大部分由预设决定，而不是由任务理解决定
- 如果规划器输出仍然浅层，`coder` 就不可能真正根据任务意图变成任务自适应
- 新增 strategy family、artifact type、debug repair 动作或 codegen 后端时，会同时触碰 analyst、DAG、registry、compiler、coder、debugger、executor、summarizer，难以局部修改和局部回滚
- 即使 codegen 逻辑变灵活，如果 artifact/verification contract 仍由固定 family 限死，前端和用户看到的交付面仍会被框架封顶

根因：

- 当前缺少一个一等公民级别的 `AnalystPlan` 合同，去真正承载：
  - 必需节点
  - 可选节点
  - 联网策略
  - 产物预期
  - 验证标准
  - 升级到动态链的理由
- `ExecutionStrategy` 当前同时像 plan、像 registry 派生结果、又像 debugger 修复状态容器，owner 不唯一
- 当前缺少不可变 `StrategyPlan`、生成期 `GenerationBundle`、调试期 `RepairDecision` 的分层
- 当前缺少“计划 -> program spec -> code bundle -> artifact verification”的冻结边界
- 当前 codegen 后端仍有 legacy renderer 与 compiler template 两套输出语义，artifact writer 还通过字符串注入挂到 legacy 路径

建议方向：

- 把纯字符串规划升级为结构化 `AnalystPlan` / `StrategyPlan`
- `Analyst/Planner` 拥有不可变 plan；DAG、registry、coder、debugger 只能消费或编译 plan，不得重新决定主策略归属
- DAG 至少先消费 plan 中的 required/optional static steps；长期引入 `WorkflowPlan` / `GraphPlan`
- Registry 只把 `StrategyPlan` 编译成 `GenerationBundle`，不得回写 plan owner 字段
- artifact/verification/program intent 由 plan 或 plan compiler 生成并冻结；coder 只从冻结 plan/spec 生成 code bundle
- 产物合同要允许任务特化交付物，例如：
  - 报告
  - 表格
  - 图表
  - 诊断产物
  - 中间导出物
  - 来源引用
  - 对账 / 归因轨迹
- 收敛 static codegen 到统一 sandbox runtime helper/API；legacy renderer 退化为 adapter，不再通过字符串注入改写输出
- Debugger 只产 `RepairDecision`，不得直接重定义主策略归属，除非明确进入受控 legacy fallback

近期修正状态（2026-04-28）：

- 原问题 6“动态链回流静态链后容易坍缩回模板 static codegen”已不再作为独立 open issue 保留。
- `DynamicResumeOverlay` 已补上 `strategy_family`、`recommended_static_action`、`skip_static_steps`，并成为 dynamic -> static handoff 的优先合同。
- 动态回流目标已收窄为 `analyst` / `coder`，不会回到 `data_inspector`、`kag_retriever` 或 `static_evidence`。
- `build_static_generation_bundle()` 已读取 dynamic overlay 的 `strategy_family`，不会再让 registry 推导覆盖 dynamic 的策略意图。
- 剩余风险并入本问题：dynamic handoff 可以影响策略和路由，但静态 codegen 仍受 `AnalystPlan` 缺失、固定 family、双后端模板和 coder 边界过载限制。

新增 finding：legacy strategy family 的删除需要迁移窗口。

- `legacy_dataset_aware_generator` 在当前 `resolve_strategy_family()` 推断路径中几乎不会作为正常业务策略被选中，它更像未知/默认/fallback 标记。
- 不能直接从 `StrategyFamily` Literal 和默认值里删除它，因为旧 checkpoint 里的 `ExecutionStrategy.strategy_family` 可能已经持久化为该值；删除后 Pydantic 读取旧数据会 validation error，checkpoint replay 会挂。
- 多个合同默认值仍写死 `legacy_dataset_aware_generator`，硬删会牵动 `ExecutionStrategy`、`ArtifactPlan`、`VerificationPlan`、`GeneratorManifest`、`StaticProgramSpec` 等默认链。
- 正确做法是先做 schema migration：读取旧 checkpoint 时把 legacy 值迁移成真实推断出的 `strategy_family`，迁移窗口结束后再移除 Literal 值和默认值。
- 当前保留 legacy 是兼容旧数据的安全惰性，不代表它仍是有业务语义的正常策略。

#### 4. DeerFlow 目前仍然是运行时依赖，而不只是被抽取思想

严重级别：HIGH

证据：

- `src/dag_engine/nodes/dynamic_swarm_node.py:123`
- `src/dynamic_engine/supervisor.py:141`
- `src/dynamic_engine/deerflow_bridge.py:98`
- `src/dynamic_engine/deerflow_bridge.py:267`
- `docs/explanation/architecture.md:173`

问题说明：

- 当前动态路径并不是 lite-interpreter 自己的原生探索循环
- 它本质上还是一个对 DeerFlow sidecar HTTP streaming 的受控适配层
- `supervisor`、`bridge`、`trace_normalizer`、状态补丁机制都围绕这个外部运行时边界设计出来

为什么重要：

- 动态能力现在还不是主运行时自己拥有的能力
- 架构仍然对外部 harness surface 有较深依赖
- 这会增加耦合、运维复杂度和后续迁移成本

根因：

- 系统先采用了 DeerFlow 作为受控运行时集成，但还没有把真正有价值的模式完全内化

建议方向：

- 保留 DeerFlow 的思想：
  - 多步探索
  - 观察 / 反思 / 再规划
  - 工具预算
  - 轨迹采集
  - 回流静态链的结构化交接
- 但要逐步移除 DeerFlow 作为长期运行时 owner 的地位
- 用内部的 `dynamic_exploration_node` 替代当前 `dynamic_swarm`

#### 5. 静态链与动态链的路由分工仍未真正解耦

严重级别：HIGH

证据：

- `src/runtime/analysis_runtime.py:544`
- `src/runtime/analysis_runtime.py:570`
- `src/runtime/analysis_runtime.py:577`
- `src/dag_engine/nodes/router_node.py:62`
- `docs/explanation/architecture.md:141`

问题说明：

- 动态升级现在仍然主要从关键词 / complexity hit 开始触发
- 一旦 `iterative_hits` 命中，粗分流路径就会优先打到 dynamic
- 文档里写的是“静态链优先”，但实现仍然会过早把任务推向动态链

近期实证（2026-04-26）：

- 一个典型的开放研究问题：`分析当前美国的经济走向`
  在没有本地结构化数据、也没有业务文档输入时，最初会被错误分到 `need_more_inputs`
- 这个误判不是因为任务真的依赖用户私有资料，而是因为分类器先看“有没有本地输入”，没有先判断“该问题是否可以靠公开外部事实自行研究”
- 由此衍生出两类实际产品问题：
  - 用户看到的是 `input_gap_report.md` / `requested_inputs.json` 产物，但任务终态却被错误标成 `success`
  - 前端会把一个本质上“等待人工补资料”或“应改走动态研究”的问题，误展示成“分析已完成”
- 为了止血，代码层一度需要把 `美国经济 / 宏观经济 / 经济走向` 这类 query 补进动态研究信号词表；
  这再次证明当前 routing 依赖关键词命中的做法只能应急，不能作为长期架构
- 更合理的判据应该是：
  - `need_more_inputs` 只留给明确依赖用户私有输入 / 内部文档的问题
  - 可由公开事实、行业信息、宏观数据自行补足的问题，优先进入 `dynamic_research_analysis`

为什么重要：

- 一批本应由以下方式解决的任务：
  - 轻量 schema inspection
  - 规则查找
  - 单次外部取证
  - 常规确定性 codegen
  仍然离“被送进 dynamic”过近

根因：

- routing 仍然更像“分类到不同模式”，而不是“沿能力梯度逐层升级”

建议方向：

- 把现有 routing 改造成能力梯度：
  - `static_only`
  - `static_with_network`
  - `dynamic_exploration_then_static`
  - `dynamic_only`

#### 7. 依赖真相源分裂，而且部分内容不可移植

严重级别：HIGH

证据：

- `pyproject.toml:7`
- `requirements.txt:97`
- `requirements.txt:100`
- `requirements.txt:115`
- `requirements.txt:135`
- `requirements.txt:216`

问题说明：

- `pyproject.toml` 只声明了两个极简依赖
- `requirements.txt` 却固定了约 250 个包
- 其中还有一个绝对本地路径依赖
- 依赖版本约束之间也没有清晰对齐

为什么重要：

- 安装可复现性很弱
- CI、开发机、Docker 环境都可能运行在不同依赖集合上
- 核心运行时与可选 heavyweight feature 的边界不清晰

根因：

- 仓库当前仍然混用了“原型期环境快照”和“产品化包装信号”

建议方向：

- 统一依赖真相源
- 把依赖拆分为：
  - core
  - docs / OCR
  - ML / heavy
  - dev / test

#### 8. MCP 工具执行没有在 registry 边界做强制授权

严重级别：HIGH

证据：

- `src/mcp_gateway/mcp_server.py:48`
- `src/mcp_gateway/mcp_server.py:98`
- `src/mcp_gateway/mcp_server.py:116`
- `src/mcp_gateway/mcp_server.py:140`

问题说明：

- registry 只检查 tool 名是否存在
- 它没有在 dispatch 边界强制要求 capability authorization
- `sandbox_exec` 虽然自己的 handler 是 governed 的，但 registry 本身不是一个 fail-closed 的硬授权门

为什么重要：

- governance 目前更多依赖调用者自觉
- 只要内部调用链能摸到 `default_mcp_server`，就有机会绕开 profile-level capability allowlist

根因：

- authz 与 invocation 被分离了，但 invocation 层没有 fail-closed

建议方向：

- 让 `call_tool` 强制要求执行上下文
- 在 dispatch 时解析 capability_id 与 profile
- 无上下文时默认拒绝

### 二、中优先级问题

#### 9. 联网能力已经存在，但还不是 DAG 原生的一等研究层

严重级别：MEDIUM

证据：

- `src/dag_engine/nodes/static_evidence_node.py:57`
- `src/dag_engine/nodes/static_evidence_node.py:78`
- `src/dag_engine/nodes/static_evidence_node.py:105`
- `src/mcp_gateway/tools/web_fetch_tool.py:62`
- `src/mcp_gateway/tools/web_fetch_tool.py:108`

问题说明：

- 当前联网检索主要以以下形式存在：
  - `static_evidence_node`
  - `web_search`
  - `web_fetch`
- 这还是一个有界单次取证分支，而不是 DAG 原生的通用研究能力

为什么重要：

- 静态链与动态链还无法共享一个统一的 research abstraction
- 网络证据收集目前仍然更像 side path，而不是 orchestration primitive

根因：

- 联网支持是作为 `static_evidence` 的战术增强加进去的，不是作为核心 DAG research node family 被设计进去的

建议方向：

- 引入 DAG 原生的 research layer：
  - source discovery
  - retrieval
  - deduplication
  - citation bundle
  - confidence / freshness metadata

#### 10. Sandbox 治理配置面对操作者来说有误导性

严重级别：MEDIUM

证据：

- `config/harness_policy.yaml:54`
- `src/harness/governor.py:141`
- `src/harness/governor.py:148`
- `src/harness/governor.py:167`

问题说明：

- YAML 中声明了语义级 deny knobs：
  - `deny_modules`
  - `deny_builtins`
  - `deny_methods`
- 但 governor 实际只执行 substring `deny_patterns` 和代码长度限制

为什么重要：

- 操作者可能以为自己修改了 YAML 就已经改变了运行时策略
- 实际上这些策略在治理层并未真正生效

根因：

- 配置面先演化出来了，但执行层和 AST 审计层还没完全接上

建议方向：

- 要么把这些 knobs 真正接通到 AST auditor / security policy merge 路径
- 要么明确移除 / 标注为 inactive placeholder，并补 policy conformance tests

#### 11. 任务调度仍缺少明确的背压合同

严重级别：MEDIUM

证据：

- `config/settings.py:88`
- `src/api/services/task_flow_service.py:58`
- `src/api/services/task_flow_service.py:247`
- `src/api/services/task_flow_service.py:299`

问题说明：

- 当前有一个固定大小的 task-flow worker pool
- task 会先 claim lease 再 submit 执行，但 API / 产品层没有强表达“排队 / 运行中 / 饱和”的状态语义

为什么重要：

- 在负载稍高时，用户可能看到任务“被接受了”，但不知道它其实只是在排队
- lease heartbeat 与积压之间的行为会变得不透明

根因：

- 当前已经定义了 execution ownership，但 queueing / saturation 还不是一等产品 / 运行时概念

建议方向：

- 增加 queue state 与 queue metrics
- 应用侧合同显式暴露 queued vs running
- 定义任务饱和与拒绝策略

#### 12. 应用侧 presenter 仍承担过多聚合与文件系统感知逻辑

严重级别：MEDIUM

证据：

- `src/api/app_presenters.py:243`
- `src/api/app_presenters.py:355`
- `src/api/app_presenters.py:403`
- `docs/reference/project-status.md:84`

问题说明：

- presenter 当前不仅做 schema 映射，还做：
  - output shaping
  - event shaping
  - workspace asset aggregation
  - filesystem upload discovery

为什么重要：

- app-facing API 是稳定产品合同
- 如果 presenter 同时负责聚合、过滤、文件系统发现和 copy shaping，后续字段漂移和 scoping mistake 的概率会升高

根因：

- read-model aggregation 还没有被彻底拆到专门的 read-model builder / repository 层

建议方向：

- 让 presenter 变薄
- 聚合与发现逻辑下沉到 read-model service / repository

#### 13. Artifact reference 虽然做了 sanitize，但本质仍是 path-oriented

严重级别：MEDIUM

证据：

- `src/common/control_plane.py:673`
- `docs/explanation/architecture.md:249`

问题说明：

- 当前系统已经能阻止任意绝对路径泄漏
- 但内部 artifact identity 依然是 path-centric 的

为什么重要：

- path-oriented identity 很脆弱
- 未来一旦 projection 层改动，仍有把宿主机布局意外带出的风险

根因：

- artifact 的所有权模型仍然更接近“文件系统输出跟踪”，而不是“领域对象”

建议方向：

- 切到 opaque artifact ID + metadata
- 绝对路径只保留在 server-side lookup 逻辑内部

#### 14. 文档已经再次出现 verification baseline 漂移

严重级别：MEDIUM

证据：

- `docs/reference/project-status.md:11`
- 本轮本地运行 pytest 得到 `260 passed, 4 skipped`

问题说明：

- 文档写的是 `255 passed, 4 skipped`
- 本轮审计实际跑出来的是 `260 passed, 4 skipped`

为什么重要：

- 这个文件明确把自己定义成唯一 truth source
- 一旦 truth-source 文档漂移，仓库就会再次回到“文档和现实两套真相”的状态

根因：

- 当前状态基线更新仍然是手工行为，没有被 release gate 严格约束

建议方向：

- 立即更新当前文档基线
- 决定是否自动化，或者把状态文档更新纳入严格发版门禁

### 三、低优先级问题

#### 15. 当前没有在已审计表面看到明确的 CI / release gate 合同

严重级别：LOW

证据：

- 审查范围内没有 `.github/workflows/*`
- `Makefile` 有多个局部命令，但没有唯一 `verify` 入口

为什么重要：

- 贡献者可能只跑部分检查
- 发布信心过于依赖人工自律

建议方向：

- 增加一个 canonical `make verify`
- 再把它接入 CI

#### 16. Prometheus 配置看起来处于半接线或残留状态

严重级别：LOW

证据：

- `config/settings.py:79` 里 `PROMETHEUS_PORT = 8000`
- `Makefile:2` 里 API 默认也是 `8000`
- 本轮搜索到了 metrics 定义，但没有在已审计范围内看到明确 metrics server startup path

为什么重要：

- 观测配置容易误导人
- 未来如果启用，默认端口会与 API 冲突

建议方向：

- 要么把 metrics 作为 FastAPI `/metrics` 暴露
- 要么单独起 metrics server，并使用不同端口并写清文档

#### 17. Settings 解析对坏环境变量不够稳健

严重级别：LOW

证据：

- `config/settings.py:22`
- `config/settings.py:32`
- `config/settings.py:49`

问题说明：

- malformed int / float / JSON env var 会在 import 阶段直接失败，而且错误上下文不够友好

为什么重要：

- 部署和本地启动会更脆弱

建议方向：

- 增加 typed validation 或更明确的错误包装

## 根因地图

把这些问题拉通后，可以归并成五个更深层的根因：

1. 控制对象已经开始存在，但太多仍然是 compatibility wrapper，而不是主导权真正所在的 primary ownership contract
2. 静态执行比以前更安全，但灵活性仍然被 renderer / registry 模板结构封顶
3. 动态研究已经被 bounded，但仍没有内生化为 lite-interpreter 自己的 runtime primitive
4. 应用侧投影与 artifact identity 仍然偏重、偏 path-coupled
5. 运行时之外的工程真相仍然分散在：
   - `pyproject.toml`
   - `requirements.txt`
   - 文档
   - `Makefile`
   - `docker-compose.yml`

## 推荐整改顺序

### P0

1. 引入 `AnalystPlan`，并让 DAG / codegen 真正消费它
2. 把 routing 重构成能力梯度
3. 内生化 `dynamic_exploration_node`，启动 DeerFlow 退场路径
4. 在 MCP dispatch 边界强制 capability auth
5. 统一依赖真相源

### P1

6. 用 planner-driven artifact contract 替代固定 artifact families
7. 把 research / network 提升为 DAG-native capability nodes
8. 把 read-model aggregation 从 presenters 中拆出去
9. 修正 compose 默认暴露和 dev-only 部署姿态

### P2

10. 增加统一 CI / release gate
11. 清理 observability 配置
12. 加强 settings validation 与 operational preflight

## 最终结论

这个项目已经具备一条可信的架构主脊梁，而且产品边界比大多数原型清楚得多；但它仍然携带足够多的 ownership drift、runtime coupling、dependency fragmentation 和 project-level operational looseness，因此更适合被视为“正在快速工程化收口的分析运行时原型”，而不是“已经达到生产级的平台”。

在进入生产级发布前，至少需要先解决这些阻断项：

- `AnalystPlan` 的主导权问题
- 静态链 / 动态链 的彻底解耦
- `dynamic_exploration_node` 的内生化方案
- MCP 授权边界的强制执行
- 依赖 / 配置 真相源统一
- compose / 默认口令 的加固
- truth-source 文档重新同步

---

## 补充审查：圆桌与 gstack 健康 / CSO 视角

补充日期：2026-04-24

### 补充审查方法

本轮在既有审计基础上补跑了以下视角：

- `code-review` / `code-review-and-quality`：实现质量、合同漂移、维护性、错误处理
- gstack `health`：质量门、测试门、格式门、前端构建与发布健康
- gstack `cso --comprehensive` 思路：secrets、依赖供应链、CORS/auth、sandbox、MCP、SSRF、路径泄漏
- 圆桌角色：架构席、安全席、测试发布席、实现质量席

说明：本轮曾尝试使用 Codex native subagents 并行审查；受当前 API Key 并发限制，架构席和实现席由主审在本地补审，测试发布席完成独立审查，安全席按 CSO 清单由主审本地补跑。

### 补充验证证据

本轮新增执行的本地验证：

- `conda run -n lite_interpreter python -m ruff check src tests scripts config`
  - 结果：通过
- `conda run -n lite_interpreter python -m ruff format --check src tests scripts config`
  - 结果：失败，50 个文件 would reformat
- `conda run -n lite_interpreter python -m pytest -q`
  - 结果：`260 passed, 4 skipped`
- `conda run -n lite_interpreter python -m pytest -q tests/test_docs_consistency.py`
  - 结果：`2 passed`
- `cd apps/web && npm run lint && npm run build`
  - 结果：通过
- `cd apps/web && npm audit --audit-level=moderate --omit=dev`
  - 结果：`found 0 vulnerabilities`
  - 注意：当前 shell 环境设置了 `NODE_TLS_REJECT_UNAUTHORIZED=0`，audit 过程出现 TLS 校验关闭警告；这削弱供应链扫描证据强度
- `conda run -n lite_interpreter python -m pip_audit --version`
  - 结果：失败，当前环境未安装 `pip_audit`
- `conda run -n lite_interpreter python -m pip check`
  - 结果：失败，报告 `typer/click`、`aliyun-log-python-sdk/protobuf`、`opencv-python-headless/numpy` 版本约束冲突
- `make test-docker`
  - 结果：失败，目标引用不存在的 `tests/test_e2e.py::test_static_task_flow_e2e_via_api_with_real_sandbox`

### 补充发现

#### 18. 前端关键 `src/lib` 代码被 `.gitignore` 屏蔽，clean checkout 发布风险很高

严重级别：HIGH

证据：

- `.gitignore:20`
- `apps/web/src/app/App.tsx:7`
- `apps/web/src/app/App.tsx:8`
- `apps/web/src/app/App.tsx:9`
- `apps/web/src/app/App.tsx:10`
- `apps/web/src/components/ui.tsx:10`
- 本轮执行 `git ls-files apps/web/src/lib` 返回空
- 本轮执行 `git check-ignore -v apps/web/src/lib/api.ts` 命中 `.gitignore:20:lib/`

问题说明：

- 前端源码大量依赖 `@/lib/api`、`@/lib/types`、`@/lib/query-client`、`@/lib/utils`
- 这些文件实际存在于 `apps/web/src/lib/`，但被根 `.gitignore` 的通用 `lib/` 规则忽略
- 当前本地 `npm run build` 能通过，是因为工作区里存在未跟踪文件；干净 clone、CI 或打包环境可能直接缺文件失败

为什么重要：

- 这是发布可复现性问题，不是单纯 Git hygiene
- 当前“前端构建通过”的证据依赖本机未跟踪源码，无法证明仓库本身可构建

建议方向：

- 把 `.gitignore` 的 `lib/` 收窄为 Python 构建产物语义，例如 `/lib/` 或特定 build 路径
- 显式跟踪 `apps/web/src/lib/*`
- 在 CI 中增加 clean checkout 的 `npm ci && npm run lint && npm run build`

#### 19. 内置前端静态挂载与全局 API auth 中间件存在产品部署冲突

严重级别：HIGH

证据：

- `config/settings.py:98`
- `src/api/auth.py:167`
- `src/api/auth.py:168`
- `src/api/main.py:67`
- `src/api/main.py:95`
- `docs/how-to/deployment.md:139`

问题说明：

- `API_AUTH_REQUIRED` 默认是 `true`
- `ApiAuthMiddleware` 只显式放行 `/health`
- `src/api/main.py` 在 `apps/web/dist` 存在时把静态前端挂到 `/`
- 部署文档写的是“可以直接打开后端地址查看页面”
- 但浏览器初次请求 `/` / 静态资源时无法附带应用内配置的 Bearer token；如果 auth middleware 对静态资源同样生效，内置前端会在入口 HTML 阶段被 401/403/503 阻断

为什么重要：

- 这会让“单后端托管前端”的部署形态与认证默认值互相冲突
- 当前主要验证是 Vite dev server / 构建检查，不能覆盖这个运行时入口问题

建议方向：

- 明确二选一：
  - 后端只服务 API，前端由独立静态站点托管
  - 或者静态资源路径在 auth middleware 中单独放行，API 仍强制鉴权
- 为 `GET /`、静态 asset、`/api/app/session` 增加认证开关组合测试
- 修正文档中“直接打开后端地址”的前提条件

#### 20. `web_search` 没有落实 allowlist 过滤，静态取证边界不完整

严重级别：HIGH

证据：

- `src/mcp_gateway/tools/web_fetch_tool.py:108`
- `src/mcp_gateway/tools/web_fetch_tool.py:111`
- `src/mcp_gateway/tools/web_fetch_tool.py:123`
- `src/mcp_gateway/tools/web_fetch_tool.py:142`
- `src/mcp_gateway/tools/web_fetch_tool.py:150`
- `src/dag_engine/nodes/static_evidence_node.py:115`
- `src/dag_engine/nodes/static_evidence_node.py:121`
- `src/dag_engine/nodes/static_evidence_node.py:126`

问题说明：

- `WebSearchTool.run()` 接收 `allowlist` 参数，但搜索结果组装时没有用 `_domain_allowed()` 过滤返回 URL
- `static_evidence_node` 会把 `allowed_domains` 传给 `web_search`，但随后直接把搜索结果写入 evidence records
- 相比之下，`web_fetch` 会校验 URL scheme 和 domain allowlist

为什么重要：

- 当前 allowlist 对 search discovery 阶段不是硬边界
- 即使 `web_fetch` 被限制，搜索 snippet / URL metadata 仍可能把非允许域内容带入后续 codegen / summarizer 上下文
- 对 LLM/agent 运行时而言，这属于外部证据投毒面，而不只是普通搜索质量问题

建议方向：

- 在 `WebSearchTool.run()` 内按 allowlist 过滤 `result.url`
- 对被过滤结果记录审计计数，而不是静默丢弃
- 为 `web_search` 增加“返回非 allowlist 域名时必须过滤”的单测

#### 21. 发布门禁目标引用已删除测试，`make test-docker` / `make test-integration` 不可信

严重级别：HIGH

证据：

- `Makefile:33`
- `Makefile:36`
- 本轮执行 `make test-docker` 失败：`file or directory not found: tests/test_e2e.py::test_static_task_flow_e2e_via_api_with_real_sandbox`
- 当前 `tests/` 下没有 `tests/test_e2e.py`

问题说明：

- Makefile 声称提供 Docker / integration gate
- 但关键 e2e 用例路径已经不存在
- 这会让“运行了 integration gate”这件事在实际发版时失真

为什么重要：

- 沙箱执行、真实 Docker、本地 HTTP e2e 是这个项目的高风险路径
- gate 失效时，全量 pytest 绿色不能等价于发布级验证绿色

建议方向：

- 恢复对应 e2e 用例，或把 Makefile 目标改到现存测试
- 把 `make test-docker` / `make test-integration` 纳入 CI
- CI 输出应区分“环境 skip”与“目标不存在 / 没跑到”

#### 22. Python 依赖环境已出现实际冲突，供应链扫描能力也缺口明显

严重级别：HIGH

证据：

- `pyproject.toml:7`
- `requirements.txt:135`
- `requirements.txt:138`
- 本轮 `conda run -n lite_interpreter python -m pip check` 失败：
  - `typer 0.15.4` 要求 `click<8.2`，但环境为 `click 8.3.1`
  - `aliyun-log-python-sdk 0.8.8` 要求 `protobuf<4.0.0`，但环境为 `protobuf 6.33.6`
  - `opencv-python-headless 4.13.0.92` 要求 `numpy>=2`，但环境为 `numpy 1.26.4`
- 本轮 `python -m pip_audit --version` 失败：未安装 `pip_audit`

问题说明：

- 既有审计已指出依赖真相源分裂；本轮进一步确认当前可运行环境本身也不是依赖约束一致状态
- `requirements.txt` 中仍有本机 `file://` 构建来源和标准库 backport 包，说明它更像环境快照而不是可移植锁文件
- Python CVE 扫描工具也没有进入默认健康门

为什么重要：

- 当前“测试通过”不能证明依赖约束是可复现、可审计、可迁移的
- 真实部署或新机器重建环境时，可能出现与本机不同的解析结果

建议方向：

- 统一依赖来源，明确 `pyproject.toml` / lock / requirements 各自职责
- 移除不可移植 `file://` 依赖和无必要 backport
- 把 `pip check` 与 Python vulnerability audit 加入 `make verify` / CI

#### 23. app-facing 资料库仍向前端暴露宿主机文件路径

严重级别：MEDIUM

证据：

- `src/api/app_schemas.py:155`
- `src/api/app_schemas.py:161`
- `src/api/app_presenters.py:472`
- `apps/web/src/lib/types.ts:121`
- `apps/web/src/pages/AssetsPage.tsx:93`

问题说明：

- `AssetListItem` app-facing schema 包含 `filePath`
- presenter 会把 server-side upload path 透传给前端
- 前端资料库页面会直接展示 `asset.filePath`

为什么重要：

- 既有审计已经指出 artifact identity 偏 path-oriented；本轮发现资料库列表也有同类问题
- 文件系统布局、tenant/workspace 路径、部署目录等不应作为稳定产品合同暴露给浏览器

建议方向：

- 从 app-facing schema 移除 `filePath`，改为 opaque asset id、display name、kind、readiness
- 如确需排障路径，应放到 admin-only diagnostics，而不是普通资料库列表
- 增加测试确保 `/api/app/assets` 不返回绝对路径

#### 24. 文档一致性测试只能防止“多处硬编码基线”，不能防止唯一真相源本身过期

严重级别：MEDIUM

证据：

- `docs/reference/project-status.md:11`
- `docs/reference/project-status.md:13`
- `tests/test_docs_consistency.py:15`
- `tests/test_docs_consistency.py:18`
- `tests/test_docs_consistency.py:35`
- 本轮实际全量回归：`260 passed, 4 skipped`

问题说明：

- `project-status.md` 仍写 `255 passed, 4 skipped`
- `tests/test_docs_consistency.py` 只保证其它文档不硬编码通过数，并要求主文档引用 truth source
- 它不会验证 truth source 中的基线是否等于最近一次测试结果

为什么重要：

- 这个仓库明确把 `docs/reference/project-status.md` 当成当前状态唯一真相源
- 如果唯一真相源本身过期，现有 consistency gate 仍然绿色

建议方向：

- 立即把当前基线更新为 `260 passed, 4 skipped`
- 后续把测试摘要生成为 CI artifact，或要求 release checklist 同步更新该文件
- 扩展 docs consistency：检查 AGENTS 中列出的高风险同步面，而不仅是几个主文档引用

#### 25. 前端没有自动化测试套件，产品面回归主要依赖 lint/build 与人工 smoke

严重级别：MEDIUM

证据：

- `apps/web/package.json:6`
- `apps/web/package.json:8`
- `apps/web/package.json:10`
- `docs/how-to/testing.md:120`

问题说明：

- 前端脚本只有 `dev` / `build` / `preview` / `lint`
- 文档也明确说明当前没有单独前端单元测试套件

为什么重要：

- 页面状态、路由跳转、React Query 缓存、错误展示和 workspace 切换不能靠 TypeScript build 充分覆盖
- app-facing API 字段一旦漂移，前端运行时失败可能晚于后端测试暴露

建议方向：

- 增加 Vitest + React Testing Library，优先覆盖 `apps/web/src/lib/api.ts` 与关键页面状态
- 增加 1 条 Playwright happy path：登录配置、上传资料、创建分析、查看详情/事件/产物
- 把前端 test 加入统一 `make verify`

#### 26. 真实 DeerFlow sidecar / 动态运行时集成仍缺少稳定发布级验证

严重级别：MEDIUM

证据：

- `tests/test_deerflow_sidecar.py:26`
- `tests/test_deerflow_sidecar.py:103`
- `tests/test_deerflow_bridge.py:98`
- `tests/test_deerflow_bridge.py:132`
- 本轮全量 pytest 中 `tests/test_deerflow_bridge.py:111` 因本地 TCP bind 不可用被 skip

问题说明：

- 当前 DeerFlow sidecar 测试大量使用 fake client、monkeypatch streaming response、patched `httpx.stream`
- 默认回归能覆盖 contract shape，但不能稳定证明真实 sidecar 进程 + HTTP/NDJSON streaming + runtime handoff 可用

为什么重要：

- 既有审计指出 DeerFlow 仍是运行时依赖；只用 fake contract 很难支撑发布级信心
- 动态路径一旦出问题，静态链绿色并不能覆盖动态研究退化

建议方向：

- 增加独立 integration job，真实启动 `scripts/run_deerflow_sidecar.py`
- 校验 `/health`、流式接口、桥接层事件归一化、回写 Blackboard 的完整路径
- 将环境能力不足的 skip 作为 CI 可见风险，而不是普通绿色

#### 27. 格式门当前失败，代码风格健康与 lint 健康不一致

严重级别：MEDIUM

证据：

- `Makefile:45`
- `Makefile:48`
- 本轮 `ruff check src tests scripts config` 通过
- 本轮 `ruff format --check src tests scripts config` 失败，报告 50 个文件 would reformat

问题说明：

- lint gate 绿色，但 format gate 红色
- 这说明代码库当前没有处在“提交即可通过格式门”的状态

为什么重要：

- 如果后续 CI 接入 `fmt-check-all`，当前分支会失败
- 如果不接入格式门，跨文件重构会持续制造噪声 diff

建议方向：

- 单独做一次格式化提交，避免和功能改动混杂
- 把 `fmt-check-all` 加入统一 verify gate
- 对生成代码目录继续保留必要的 per-file ignore / exclude，避免格式化生成物造成无意义 churn

#### 28. 单一健康 / 发布入口仍缺席，质量信号需要人工拼接

严重级别：LOW

证据：

- `Makefile:30`
- `Makefile:45`
- `Makefile:48`
- `apps/web/package.json:6`
- `pyproject.toml:12`
- `pyproject.toml:14`

问题说明：

- 后端测试、ruff lint、ruff format、docs consistency、前端 lint/build、dependency audit、Docker/integration gate 分散在多个命令中
- `pyproject.toml` 的 pytest 配置没有 coverage 门槛
- Makefile 没有 `verify` / `health` 聚合目标

为什么重要：

- 审计和发版时容易遗漏某个质量面
- 健康趋势无法稳定量化，也不利于后续多 agent 协作

建议方向：

- 增加 `make verify`：后端 lint/format/test、docs consistency、前端 lint/build/test、dependency checks
- 增加 CI artifact：JUnit、coverage、前端构建摘要、dependency audit 摘要
- 使用 gstack `health` 输出的分类评分作为人工审查辅助，而不是替代原生命令

### 补充评分

| 维度 | 分数 | 依据 |
| --- | ---: | --- |
| 架构边界 | 6.5/10 | 主骨架清楚，但 AnalystPlan、动态内生化、artifact/read-model 边界仍未彻底收口 |
| 安全与信任边界 | 6.2/10 | auth/scope/sandbox 有明显进展，但 MCP dispatch、web_search allowlist、路径暴露、供应链扫描仍有缺口 |
| 测试健康 | 7.2/10 | 后端全量回归与前端 lint/build 绿色，但 e2e/sidecar/front-end tests/coverage gate 不足 |
| 维护性 | 6.8/10 | 文档结构比原型期清楚，但格式门失败、依赖冲突和 untracked 前端核心代码削弱可维护性 |
| 发布就绪度 | 5.8/10 | 当前更像本地可运行状态，而不是 clean checkout + CI + dependency audit + integration gate 全绿状态 |

### 补充结论

本轮补充审查没有推翻原审计的主判断：项目已经有清晰主脊梁，但仍未达到生产级稳定平台。补充发现进一步说明，当前最大的新增风险集中在“仓库可复现性”和“发布门禁真实性”：

- 前端关键源码被忽略规则挡在版本控制外
- 内置静态前端托管与 API auth 默认值可能互相冲突
- Docker / integration gate 已引用不存在测试
- Python 环境实际存在依赖冲突
- 静态取证 search allowlist 没有真正执行

因此，在原 P0 列表之外，应追加两个生产前阻断项：

1. 修复 clean checkout 可构建性：跟踪 `apps/web/src/lib/*`，并用 CI 验证前端 clean build
2. 修复 release gate 真实性：恢复 / 替换失效 e2e 目标，建立 `make verify` 并接入 CI

---

## 补充审查二：DAG / Coder / Debugger 架构设计专项

说明：本节是对上一轮补充审查的纠偏，只审查架构设计问题；不讨论依赖、CI、格式、Docker、环境可复现性等发布健康议题。本节综合了接口/边界设计技能、架构圆桌与批判圆桌的结论，重点覆盖 DAG 编排、节点合同、coder/debugger/executor/summarizer 职责、static/dynamic handoff、checkpoint/retry/terminal 语义。

### 架构判断摘要

当前 `lite-interpreter` 的核心架构问题不是“某个节点实现不够好”，而是编排语义没有单一 owner：`dag_graph`、`DagGraphState`、`ExecutionData`、`ExecutionStrategy`、`TaskGlobalState`、legacy metadata 同时承载 routing、handoff、retry、terminal、checkpoint replay 等控制语义。结果是 DAG 看起来是图，实际更像硬编码流程脚本；coder/debugger/executor/summarizer 看起来是分工节点，实际通过松散 dict patch 和共享 blackboard 互相覆盖状态。

这会直接影响后续演进：新增一个 strategy family、artifact 类型、debug repair 动作、dynamic resume 场景，都会同时触碰 DAG、registry、compiler、executor、summarizer 和多个 schema 字段，难以局部修改、局部验证、局部回滚。

### 关键架构发现

#### 29. 已合并到问题 1：DAG 仍是硬编码流程脚本，不是 plan-driven DAG

本条与问题 1 同根：`analyst` 没有一等 `AnalystPlan` / `StrategyPlan`，DAG 也没有消费 plan 的 graph spec / edge condition / node outcome。完整证据、影响与建议已合并到问题 1，避免重复维护两套修复范围。

#### 30. 节点 I/O 合同是 dict patch soup，缺少强类型 NodeOutcome

严重级别：HIGH

证据：

- `src/dag_engine/graphstate.py:9`
- `src/dag_engine/graphstate.py:13`
- `src/dag_engine/graphstate.py:75`
- `src/dag_engine/dag_graph.py:25`
- `src/dag_engine/dag_graph.py:39`
- `src/dag_engine/nodes/coder_node.py:48`
- `src/dag_engine/nodes/debugger_node.py:87`
- `src/dag_engine/nodes/executor_node.py:115`

问题说明：

- `DagGraphState` 自称只是“瞬时传输态”，但它包含 `analysis_brief/generated_code/execution_strategy/program_spec/repair_plan/execution_record/dynamic_*` 等大量事实字段
- 节点返回任意 dict patch，DAG 再靠 `next_actions`、`blocked`、`execution_record`、`retry_count` 等字符串/键名约定解释控制流
- 没有区分 `continue`、`retryable_failure`、`terminal_failure`、`waiting_for_human`、`degraded_success` 等语义

为什么这是架构问题：

- 字段名成为隐式接口，重命名或漏填会直接改变调度行为
- checkpoint、resume、summary、UI event 都在消费同一批松散 patch，调用方无法知道某个字段是事实、派生值还是临时控制信号
- 新节点无法声明“我成功但交付未达标”“我失败但可修复”“我阻断且等待输入”这类结构化 outcome

建议方向：

- 定义 `NodeResult[TOutput]`：包含 `node_name`、`status`、`outcome`、`output`、`state_patch`、`failure`、`next_hint`
- `next_actions` 只能作为 hint，不再作为唯一控制语义
- `DagGraphState` 缩小为身份、trace、临时传输字段；事实写入必须经 typed blackboard accessor

#### 31. checkpoint replay 没有输入摘要、合同版本和语义 outcome，恢复正确性不可证明

严重级别：HIGH

证据：

- `src/blackboard/schema.py:237`
- `src/blackboard/schema.py:246`
- `src/dag_engine/dag_graph.py:50`
- `src/dag_engine/dag_graph.py:55`
- `src/dag_engine/dag_graph.py:87`
- `src/dag_engine/dag_graph.py:98`

问题说明：

- `NodeCheckpointState` 只保存 status、timestamp、attempt_count、error、output_patch
- `_run_checkpointed_node()` 只要看到 `status == "completed"` 且 patch 非空，就直接回放旧 output patch
- checkpoint 不记录上游输入 digest、ExecutionData 版本、schema/contract 版本、代码版本、policy 版本、node semantic outcome

为什么这是架构问题：

- 如果用户输入、知识快照、governance、asset mount、analysis plan 或代码版本变化，旧 checkpoint 仍可能被复用
- 恢复链路看似可靠，实际只是 patch cache；无法判断 replay 是否仍适用于当前任务事实
- 这会放大第 30 条 dict patch soup 的风险：错误 patch 一旦被缓存，会稳定污染后续节点

建议方向：

- checkpoint 增加 `input_digest`、`contract_version`、`node_impl_version`、`semantic_outcome`、`depends_on` 列表
- 只有 digest 与版本匹配时才允许 replay
- 对 router/analyst/coder/debugger/executor 使用不同 checkpoint policy；副作用节点默认不可盲目 replay

#### 32. 已合并到问题 1：`ExecutionStrategy` owner 被拆散

本条与问题 1 同根：规划、registry 编译、debug repair 共享并覆盖同一个 `ExecutionStrategy`，导致策略归属不可解释。完整证据、影响与建议已合并到问题 1。

#### 33. 已合并到问题 1：Coder 边界不清

本条与问题 1 同根：coder 仍在生成代码时同时生成或改写 strategy/spec/artifact/verification 多个控制合同。完整证据、影响与建议已合并到问题 1。

#### 34. Debugger 实际是重新生成/回退节点，不是真正的 failure-localizing debugger

严重级别：HIGH

证据：

- `src/dag_engine/nodes/debugger_node.py:35`
- `src/dag_engine/nodes/debugger_node.py:45`
- `src/dag_engine/nodes/debugger_node.py:49`
- `src/dag_engine/nodes/debugger_node.py:52`
- `src/dag_engine/nodes/debugger_node.py:74`
- `src/dag_engine/nodes/debugger_node.py:87`
- `src/common/contracts.py:327`
- `src/common/contracts.py:332`

问题说明：

- Debugger 从 `latest_error_traceback` 或 artifact verification failure 拼出 `failure_reason`
- repair action 只有 `fallback_to_legacy`、`simplify_program`、`drop_external_evidence` 这类粗粒度动作
- 随后再次调用 `prepare_static_codegen()` 整体重生代码，而不是定位失败阶段、失败 artifact、失败 step 或失败 contract

为什么这是架构问题：

- Debugger 不消费结构化失败 envelope，也不做局部 patch，因此无法稳定处理“某个 required artifact 缺失”“某个 step 输入不合法”“sandbox 执行异常”“审计规则拒绝”这类不同失败
- 修复闭环退化成“换个 generator / 简化程序再试一次”，可解释性和可扩展性都弱
- 失败原因被字符串化后，后续策略只能靠文本猜测

建议方向：

- 引入 `StaticFailureEnvelope`：包含 `origin_node`、`failure_kind`、`failed_contract`、`failed_step_id`、`repairable`、`debug_hints`
- Debugger 输出 `RepairDecision`，只允许修改 `program_spec`、`artifact_plan` 或 `renderer_config` 的限定区域
- Repair 应可被 verifier 独立验证，而不是直接再次跑完整 codegen

#### 35. Executor 同时承担执行、持久化、artifact 验证和 retry 路由，职责过载

严重级别：HIGH

证据：

- `src/dag_engine/nodes/executor_node.py:76`
- `src/dag_engine/nodes/executor_node.py:84`
- `src/dag_engine/nodes/executor_node.py:94`
- `src/dag_engine/nodes/executor_node.py:101`
- `src/dag_engine/nodes/executor_node.py:111`
- `src/dag_engine/nodes/executor_node.py:121`

问题说明：

- Executor 负责 lease 检查、sandbox 运行、execution_record 持久化、artifact verification、latest_error_traceback 写入、决定进入 debugger 或 skill_harvester
- `verify_generated_artifacts()` 在 executor 内部调用，导致“运行成功”和“交付合同成功”两个概念被合并在同一节点
- 如果 artifact 验证失败，executor 直接把 next action 设为 debugger

为什么这是架构问题：

- executor 难以替换为其它 runtime，因为它不仅是 runtime adapter，还是 verifier 与 repair router
- sandbox 执行失败、artifact 合同失败、lease 失败、无代码失败会走不同隐式路径，缺少统一 outcome
- artifact verifier 无法作为独立质量门复用或单测其 orchestration 行为

建议方向：

- 拆成 `SandboxExecutor`、`ExecutionRecorder`、`ArtifactVerifier`、`RepairRouter`
- Executor 只输出 `ExecutionRecord` 与 runtime failure
- Verifier 独立消费 `ExecutionRecord + ArtifactPlan`，输出 `VerificationOutcome`
- RepairRouter 根据 typed failure 决定 debugger / terminal / waiting_for_human

#### 36. Executor 的“无代码可执行”前置失败被伪装成可继续路径

严重级别：MEDIUM

证据：

- `src/dag_engine/nodes/executor_node.py:70`
- `src/dag_engine/nodes/executor_node.py:73`
- `src/dag_engine/dag_graph.py:233`
- `src/dag_engine/dag_graph.py:239`
- `src/dag_engine/dag_graph.py:241`
- `src/dag_engine/dag_graph.py:248`

问题说明：

- 当没有 `exec_data` 或没有 `generated_code` 时，executor 返回 `next_actions: ["skill_harvester"]` 和 `execution_record: None`
- DAG 仍继续执行 skill_harvester 与 summarizer，最后才因 `execution_record` 缺失判定失败

为什么这是架构问题：

- 节点无法表达“前置条件不满足，立即终止/回到 coder/等待人工”的 outcome
- 下游节点会处理一个根本没有执行记录的任务，制造无意义 summary/harvest 副作用
- 这类问题会让观察者误以为链路已进入收尾阶段，而真实错误发生在 executor 前置条件

建议方向：

- Executor 返回 `terminal_failure` 或 `blocked` outcome，附 `failure_kind=no_generated_code`
- DAG 对前置条件失败直接终止或回到 coder，不再进入 harvester/summarizer happy-path
- summary 只在 terminal verdict 生成后投影，不应掩盖前置失败

#### 37. Summarizer 过载，混合终态判定、用户文案、技术投影、诊断聚合与脱敏

严重级别：HIGH

证据：

- `src/dag_engine/nodes/summarizer_node.py:134`
- `src/dag_engine/nodes/summarizer_node.py:166`
- `src/dag_engine/nodes/summarizer_node.py:247`
- `src/dag_engine/nodes/summarizer_node.py:258`
- `src/dag_engine/nodes/summarizer_node.py:348`
- `src/dag_engine/nodes/summarizer_node.py:479`
- `src/dag_engine/nodes/summarizer_node.py:511`

问题说明：

- `_build_static_response()` 同时解析 execution output、artifact outputs、business context、knowledge snapshot、rule/metric/filter checks、caveats、details
- 成功文案由 summarizer 根据 `is_debugger_fallback` 和 findings 拼接；即使 execution/artifact 层存在失败，也可能生成“已完成静态链分析”文案
- `summarizer_node()` 还负责 blackboard 写入、memory summary 存储、event_bus 发布、payload 脱敏

为什么这是架构问题：

- “执行成功”“artifact 合同成功”“可对用户展示成功”“需要人工介入”没有先形成独立 terminal verdict
- summary 既是 read model projector，又带副作用写状态/发事件/存记忆，难以单独测试
- 后续新增输出类型时，summarizer 会继续膨胀成跨层聚合器

建议方向：

- 先引入 `TerminalVerdictBuilder`：只根据 typed outcomes 生成 success/failed/waiting/degraded verdict
- 再拆 `UserResponseProjector` 与 `TechnicalDetailsProjector`
- 脱敏、memory 存储、UI event 发布放到 orchestration 收尾层，而不是 summary 文案构造函数内

#### 38. Static/dynamic handoff 双写 `resume_overlay` 与 legacy steps，回流合同没有唯一 owner

严重级别：HIGH

证据：

- `docs/reference/execution-strategy.md:99`
- `docs/reference/execution-strategy.md:103`
- `src/blackboard/schema.py:764`
- `src/blackboard/schema.py:766`
- `src/dag_engine/nodes/dynamic_swarm_node.py:95`
- `src/dag_engine/nodes/dynamic_swarm_node.py:110`
- `src/dag_engine/dag_graph.py:329`
- `src/dag_engine/dag_graph.py:337`

问题说明：

- 文档承认 v1 仍把 `resume_overlay` 与 `next_static_steps` 双写
- `ExecutionDynamicState` 同时存 `resume_overlay` 和 `next_static_steps`
- 动态节点 `_build_dynamic_patch()` 同时返回两套字段
- 静态回流时 `_merge_dynamic_research_into_static_state()` 优先读 `dynamic_next_static_steps` 或 `execution_intent.metadata.next_static_steps`，没有把 `resume_overlay` 作为唯一输入合同

为什么这是架构问题：

- dynamic -> static handoff 的真实语义分布在 overlay、legacy step list、execution_intent metadata、state patch 多处
- 一旦字段不同步，静态链会按旧步骤恢复，证据 refs、open questions、suggested actions 与实际回流计划分叉
- 这会阻碍动态研究真正成为静态链的一等前置阶段

建议方向：

- `DynamicResumeOverlay` 升级为唯一 handoff contract
- `next_static_steps` 不再持久化双写，只作为 overlay 的读时派生字段
- `_merge_dynamic_research_into_static_state()` 只接收 `DynamicResumeOverlay + DynamicResearchPacket`，禁止从多个 legacy 字段猜测

#### 39. 动态运行时把嵌套 ExecutionData 当扁平 dict 读取，导致上下文投影失真

严重级别：HIGH

证据：

- `src/dag_engine/nodes/dynamic_swarm_node.py:34`
- `src/dag_engine/nodes/dynamic_swarm_node.py:39`
- `src/blackboard/schema.py:805`
- `src/blackboard/schema.py:812`
- `src/dynamic_engine/supervisor.py:115`
- `src/dynamic_engine/supervisor.py:127`

问题说明：

- 动态节点把 `ExecutionData` 直接 `model_dump()` 成嵌套 dict
- `ExecutionData` 的真实结构是 `control/inputs/knowledge/static/dynamic`
- `DynamicSupervisor.build_inherited_context()` 却用 `execution_state.get("knowledge_snapshot")`、`execution_state.get("decision_log")`、`execution_state.get("execution_intent")` 读取顶层字段

为什么这是架构问题：

- 动态链可能拿不到持久化的 knowledge snapshot、decision log、execution intent，只能退回瞬时 state 或空值
- 这不是单个字段 bug，而是缺少 `ExecutionData -> DynamicContextInput` 显式投影层
- 后续任何嵌套 state 重构都会继续破坏 dynamic context

建议方向：

- 建立 typed projector：`build_dynamic_context_input(execution_data: ExecutionData, graph_state: DagGraphState)`
- 动态 supervisor 只能消费 `DynamicContextInput`，不得直接消费 raw `model_dump()`
- 所有 knowledge/control/dynamic 字段通过 accessor 读取，禁止自由 `dict.get()` 猜结构

#### 40. 动态 degraded preview 与 DAG terminal 语义互相矛盾

严重级别：HIGH

证据：

- `src/dag_engine/nodes/dynamic_swarm_node.py:123`
- `src/dag_engine/nodes/dynamic_swarm_node.py:127`
- `src/dynamic_engine/deerflow_bridge.py:220`
- `src/dynamic_engine/deerflow_bridge.py:239`
- `src/dynamic_engine/deerflow_bridge.py:349`
- `src/dynamic_engine/deerflow_bridge.py:352`
- `src/dag_engine/dag_graph.py:466`
- `src/dag_engine/dag_graph.py:479`

问题说明：

- 动态节点注释说明 DeerFlow 不可用时应退化为 planning preview，而不是直接让 DAG 失败
- `DeerflowBridge.preview()` 和 sidecar 异常路径都返回 `status="unavailable"`
- `execute_task_flow()` 只特殊处理 `completed` 和 `denied`；其它动态状态全部映射为 `terminal_status="failed"`

为什么这是架构问题：

- runtime degraded mode 没有进入 orchestration outcome 模型
- 系统无法表达“动态 runtime 不可用，但 preview 可展示/可等待人工/可回退静态”的中间状态
- 注释承诺与 DAG 实际终态不一致，说明动态链 outcome contract 不闭合

建议方向：

- 定义动态 outcome：`completed`、`denied`、`degraded_preview`、`runtime_failed`
- `degraded_preview` 映射到 `waiting_for_human` 或 static fallback，而不是普通 failed
- UI/event/presenter 显式展示 degraded reason 和可操作 next step

#### 41. retry 预算分裂：全局状态默认 3 次，实际审计-修复环硬编码 1 次

严重级别：MEDIUM

证据：

- `src/blackboard/schema.py:574`
- `src/blackboard/schema.py:578`
- `src/dag_engine/nodes/auditor_node.py:15`
- `src/dag_engine/nodes/auditor_node.py:37`
- `src/dag_engine/nodes/auditor_node.py:44`
- `src/dag_engine/nodes/debugger_node.py:21`
- `src/blackboard/global_blackboard.py:264`
- `src/blackboard/global_blackboard.py:275`

问题说明：

- `TaskGlobalState` 暴露 `max_retries=3/current_retries`
- `auditor_node` 内部硬编码 `MAX_DEBUG_RETRIES = 1`
- `debugger_node` 用瞬时 graph state 递增 `retry_count`
- finished event 又从 global task state 发布 retry info

为什么这是架构问题：

- retry policy、retry counter、retry event 三套来源不一致
- 前端/审计看到的预算与实际 DAG 行为不同，难以解释“为什么 3 次预算只跑 1 次”
- retry 作为控制语义不应属于单个 auditor 常量

建议方向：

- 引入唯一 `RepairLoopPolicy`，挂在 `ExecutionControlState` 或 workflow plan 上
- Auditor/Debugger/DAG/global event 都只读写同一份 repair loop state
- retry outcome 应包含 `attempt_index`、`max_attempts`、`stop_reason`

#### 42. `waiting_for_human` 在调度层是终态，在事件合同里却不是终态

严重级别：MEDIUM

证据：

- `src/api/services/task_flow_service.py:205`
- `src/api/services/task_flow_service.py:212`
- `src/blackboard/schema.py:58`
- `src/blackboard/global_blackboard.py:264`
- `src/blackboard/global_blackboard.py:285`
- `src/blackboard/global_blackboard.py:324`
- `src/blackboard/global_blackboard.py:326`

问题说明：

- Task flow 把 `terminal_status == "waiting_for_human"` 映射到 `GlobalStatus.WAITING_FOR_HUMAN`
- global blackboard 的恢复逻辑明确不把 WAITING_FOR_HUMAN 放入 unfinished tasks，说明它是稳定阻断终态
- 但 `SYS_TASK_FINISHED` 只在 `SUCCESS/FAILED` 时发布

为什么这是架构问题：

- terminal state 集合没有统一定义
- 依赖 finished event 的外部消费者会认为等待人工的任务仍未结束
- Orchestration terminal 与 event terminal 不一致，会造成监控、恢复和 UI 状态不同步

建议方向：

- 定义统一 `TerminalStatusSet = {success, failed, waiting_for_human, archived?}`
- `SYS_TASK_FINISHED` 覆盖所有稳定终态，并用 `final_status` 区分结果
- 恢复逻辑、UI presenter、event bus 使用同一个 terminal 判定函数

#### 43. 已合并到问题 1：static codegen 双后端与模板注入

本条与问题 1 同根：planner/registry/coder 没有沿不可变 plan 编译成统一 codegen 后端，导致 artifact plan、emit kind、verification、renderer/模板输出语义分散。完整证据、影响与建议已合并到问题 1。

### 根因归纳

1. 控制语义多 owner：DAG、GraphState、ExecutionData、ExecutionStrategy、GlobalState 都在保存或解释 routing/retry/terminal/handoff。
2. 节点合同弱：节点输出是任意 patch，缺少 typed outcome、typed failure、typed handoff。
3. 规划与执行混合：Analyst/Registry/Coder/Debugger 都在不同阶段重写 strategy，而不是沿不可变 plan 逐步编译。
4. 成功语义未分层：runtime success、artifact success、delivery success、user-facing success 被 executor/summarizer 混在一起。
5. 恢复机制是 patch cache，不是可验证恢复点。

### 建议整改顺序

#### P0：先收口编排控制合同

- 定义 `NodeOutcome`、`StaticFailureEnvelope`、`DynamicOutcome`、`TerminalVerdict`、`RepairLoopPolicy`
- DAG 只解释这些合同，不再靠 `next_actions` 字符串和缺省字段推断
- 统一 terminal status 集合，修复 `waiting_for_human` 事件语义

#### P1：冻结计划与策略 owner

- 把 `ExecutionStrategy` 拆为 `StrategyPlan`、`GenerationBundle`、`RepairDecision`
- Analyst/Planner 拥有 plan；Registry/Compiler 只编译；Debugger 只产 repair decision
- `DynamicResumeOverlay` 成为唯一 dynamic -> static handoff 合同

#### P2：重构 coder/debugger/executor/summarizer 边界

- Coder：只做 spec/code bundle 生成，不再同时拥有 artifact/verification/retry 语义
- Debugger：消费 typed failure，做局部 repair，不再整套复用 coder
- Executor：只执行 sandbox 并记录 execution record
- Verifier：独立验证 artifact contract
- Summarizer：只做 response projection，先消费 `TerminalVerdict`

#### P3：升级 checkpoint 与 static codegen 后端

- checkpoint 加 input digest、contract version、semantic outcome、dependency list
- static codegen 收敛到统一 runtime helper/API，legacy renderer 作为 adapter 逐步退场
- 对每个 contract 增加 focused tests：plan compile、failure routing、resume overlay、terminal verdict、checkpoint invalidation

### 架构专项结论

如果只修环境、依赖、测试门禁，项目仍会保留最核心的架构风险：DAG 不是一等 plan executor，coder/debugger/executor/summarizer 的职责边界不稳定，static/dynamic handoff 与 retry/terminal/checkpoint 语义分散。下一阶段应优先做“控制合同收口”，否则每新增一个节点或策略都会继续把复杂度压回 `dag_graph.py`、`static_generation_registry.py` 和 `summarizer_node.py`。

---

## 补充审查三：TES Lab 增量缺口复核

补充日期：2026-04-27

### Discovery Question

如何在不重复既有审计结论的前提下，发现当前工作区仍遗漏的 bug、设计错误和产品/运行时缺口，并把最值得修的内容收敛成可执行整改项？

### Assumptions

- 本节只补充“现有审计未充分覆盖”的增量问题。
- 本节默认当前产品边界仍是 Web 前端 + `/api/app/*` app-facing API。
- 本节不修改代码，只补充审计记录。

### Evaluator

本轮使用 `$tes-lab` 的轻量 ARCHLAB/SCOUT 方式，对候选问题按以下维度筛选：

| 维度 | 判据 |
| --- | --- |
| 用户影响 | 是否会让真实用户卡住、误判状态、看到错误数据或无法完成操作 |
| 安全/治理影响 | 是否削弱 auth、scope、artifact、audit、sidecar 等信任边界 |
| 可复现性 | 是否能从当前代码路径直接推出，而不是纯猜测 |
| 与既有审计差异 | 是否不是第 1-43 条的简单重复 |
| 修复可执行性 | 是否能拆成明确代码/测试/文档改动 |

候选路径里被拒绝的内容：

- 继续重复 “DAG 不是 plan-driven” 一类架构大问题：已由第 29-43 条覆盖。
- 继续重复依赖、CI、format、clean checkout 问题：已由第 18、21、22、27、28 条覆盖。
- 单纯 UI 文案偏好：缺少足够工程风险信号。

### 新增发现

#### 44. 本地免鉴权会话在前端不可自然进入，且 auth 开关语义与 token 配置耦合

严重级别：MEDIUM

证据：

- `docs/how-to/deployment.md:75`
- `docs/how-to/deployment.md:77`
- `.env.example:33`
- `.env.example:34`
- `src/api/auth.py:89`
- `src/api/auth.py:103`
- `src/api/auth.py:105`
- `apps/web/src/app/App.tsx:120`
- `apps/web/src/app/App.tsx:201`

问题说明：

- 部署文档提示可以临时设 `API_AUTH_REQUIRED=false` 做本地联调，并依赖 `API_LOCAL_TENANT_ID` / `API_LOCAL_WORKSPACE_ID` 形成默认 scope。
- 但后端 `auth_enabled()` / `authenticate_request()` 的启用条件是 `API_AUTH_REQUIRED or token_store`；只要 `.env.example` 默认的 `API_AUTH_TOKENS_JSON` 仍存在，即使 `API_AUTH_REQUIRED=false`，API 仍会进入 token auth 分支。
- 前端 `sessionQuery` 还要求 `apiBaseUrl && accessToken` 才发起 session 请求，并且 `!accessToken` 时直接停在 `SessionGate`。
- 结果是“本地免鉴权默认 scope”这个配置意图在真实前端里并不自然可达：用户要么仍被 token store 约束，要么必须输入一个无实际意义的 token 才能触发 session bootstrap。

为什么重要：

- 这会让本地联调路径和文档描述不一致。
- 新接手开发者会误以为关闭 `API_AUTH_REQUIRED` 就能进入本地模式，但实际还受默认 token 配置与前端 gate 双重影响。
- auth 开关、token store、local scope 三者语义混在一起，后续容易继续制造测试与部署分歧。

建议方向：

- 明确区分 `auth_required`、`token_store_configured`、`anonymous_local_session_enabled` 三个概念。
- 当前端允许 local dev session 时，`/api/app/session` 应能在无 access token 的情况下 bootstrap 本地 scope。
- 如果项目决定“只要配置 token store 就永远启用 auth”，需要同步修改部署文档，不要再暗示只改 `API_AUTH_REQUIRED=false` 即可。

#### 45. 输出下载链接生成早于 scope/root 校验，会向前端暴露必然 404 的可下载产物

严重级别：MEDIUM

证据：

- `src/api/app_presenters.py:256`
- `src/api/app_presenters.py:262`
- `src/api/app_presenters.py:263`
- `src/api/app_presenters.py:308`
- `src/api/app_presenters.py:313`
- `tests/test_api_app.py:595`
- `tests/test_api_app.py:643`

问题说明：

- `build_analysis_outputs()` 只要 `_resolve_output_file_path(path)` 找到本机存在的文件，就为该 output 生成 `downloadUrl` 和 `previewKind`。
- 真正的 tenant/workspace safe-root 校验在 `resolve_analysis_output_content()` 下载阶段才执行。
- 现有测试覆盖了越界 sibling path 下载时返回 404，但没有覆盖分析详情页是否应提前隐藏这个无效 `downloadUrl`。

为什么重要：

- app-facing detail response 会把一个“看起来可下载”的产物交给前端，用户点击后才得到 404。
- 这把 access-control 决策推迟到交互阶段，导致 UI 状态和服务端真实授权状态不一致。
- 对 artifact 合同而言，`downloadUrl != null` 应该表示“当前用户当前 scope 可读取”，而不只是“服务器本机存在这个路径”。

建议方向：

- 抽出统一 `resolve_scoped_output_file(task, path)`，同时服务 detail projection 和 download endpoint。
- `downloadUrl` / `previewKind` 只有在路径位于当前 tenant/workspace 的 `UPLOAD_DIR` 或 `OUTPUT_DIR` 下时才生成。
- 增加回归测试：越界 output 在 detail response 中 `downloadUrl is None`，而不是只测下载 endpoint 404。

#### 46. DeerFlow sidecar 用 `os.chdir()` 切配置目录，存在并发串扰和相对路径语义分裂

严重级别：HIGH

证据：

- `scripts/run_deerflow_sidecar.py:31`
- `scripts/run_deerflow_sidecar.py:34`
- `scripts/run_deerflow_sidecar.py:41`
- `scripts/run_deerflow_sidecar.py:44`
- `scripts/run_deerflow_sidecar.py:52`
- `scripts/run_deerflow_sidecar.py:56`
- `scripts/run_deerflow_sidecar.py:77`
- `scripts/run_deerflow_sidecar.py:89`

问题说明：

- `build_client_kwargs()` 会把相对 `config_path` 解析到 `_project_root / config_path`。
- `resolve_client_config_dir()` 却直接对相对 `config_path` 调用 `Path(...).resolve()`，它依赖当前进程 cwd。
- `deerflow_config_workdir()` 再用 `os.chdir(target_dir)` 切换进程全局 cwd，并在 `chat` 与 streaming generator 中包住 DeerFlow 调用。

为什么重要：

- ASGI 进程内多个 sidecar 请求并发时，一个请求修改 cwd 会影响其它请求、日志、相对文件读取和后续 config 解析。
- 对同一个相对 `config_path`，传给 `DeerFlowClient` 的路径和 `os.chdir()` 的目录可能基于不同基准解析。
- 这类问题在单测/fake client 中很难暴露，但真实 sidecar 长流式请求最容易踩中。

建议方向：

- 不要在服务进程里使用 `os.chdir()` 作为请求级配置隔离手段。
- 如果 DeerFlow 必须依赖 cwd，应把 sidecar 限制为单请求串行，或在独立子进程中运行每个配置上下文。
- 至少先统一相对路径解析：`resolve_client_config_dir()` 应复用与 `build_client_kwargs()` 相同的 project-root 解析逻辑。

#### 47. app-facing read-model 退化把存储故障伪装成空数据

严重级别：MEDIUM

证据：

- `src/api/app_presenters.py:408`
- `src/api/app_presenters.py:414`
- `src/api/app_presenters.py:430`
- `src/api/app_presenters.py:436`
- `src/api/app_presenters.py:496`
- `src/api/app_presenters.py:502`
- `src/api/app_presenters.py:537`
- `src/api/app_presenters.py:543`

问题说明：

- 资料、方法、审计 read-model 在遇到 `RuntimeError` 时都会记录 warning，然后退化为空列表或只展示预置方法。
- 对 `Assets` 页，跳过 execution/knowledge state 后还可能继续展示 upload 目录，用户看不到“索引态不可用”的事实。
- 对 `Audit` 页，`AuditRepo.query_records()` 失败会直接返回 `([], 0)`，治理页面呈现为“没有审计记录”。

为什么重要：

- 对业务资料库，空数据和存储不可用是两种完全不同的状态。
- 对审计页面，把审计存储故障显示为空记录会削弱治理可信度。
- 这也会让监控和前端错误处理失去信号，因为 HTTP 仍然是 200。

建议方向：

- 区分 soft degradation 与 hard failure：方法页展示预置方法可以 degraded，但审计记录不可用应返回结构化错误或带 `degraded=true` 的响应。
- app-facing schema 增加 `warnings` / `degradedSources`，让前端明确显示“部分数据源不可用”。
- 为 storage read failure 增加测试，验证用户不会把故障误解成空状态。

#### 48. `waiting_for_human` 已作为终态展示，但缺少继续、补料、取消或归档闭环

严重级别：MEDIUM

证据：

- `src/api/services/task_flow_service.py:205`
- `apps/web/src/app/App.tsx:22`
- `apps/web/src/pages/AnalysesPage.tsx:40`
- `apps/web/src/pages/AnalysisDetailPage.tsx:23`
- `src/blackboard/global_blackboard.py:325`
- `src/blackboard/global_blackboard.py:335`
- 本轮搜索 `src/api` 与 `apps/web/src`，未看到针对 `waiting_for_human` 的 resume / continue / cancel 操作入口。

问题说明：

- task flow 会把 input gap、治理阻断等路径落到 `GlobalStatus.WAITING_FOR_HUMAN`。
- 前端把 `waiting_for_human` 放入 terminal status set，详情和列表都停止轮询。
- global blackboard 恢复逻辑也明确不会自动恢复 `WAITING_FOR_HUMAN`。
- 但产品/API 侧没有一等的“补充资料后继续”“确认后重跑”“取消/归档”动作；甚至 `archive_task()` 只允许 `SUCCESS/FAILED`，不允许归档等待人工任务。

为什么重要：

- 这会把用户引入一个不可操作的阻断终态：系统说“等待人工处理”，但没有提供处理入口。
- 任务不会自动恢复，前端也停止轮询，因此除非开发者手工改状态，否则任务可能永久滞留。
- 这不是单纯事件语义问题，而是产品闭环缺口。

建议方向：

- 为 `waiting_for_human` 定义明确用户动作：补充 asset 后 resume、确认静态 fallback、取消、归档。
- app-facing API 增加对应端点和审计记录。
- `archive_task()` 或新的 cancel/archive policy 应覆盖 `WAITING_FOR_HUMAN`，并补测试。

#### 49. 工作台运行/复核指标只基于第一页数据，容易与真实总量不一致

严重级别：LOW

证据：

- `src/api/routers/app_router.py:151`
- `src/api/routers/app_router.py:152`
- `src/api/routers/app_router.py:167`
- `src/api/routers/app_router.py:169`
- `apps/web/src/lib/api.ts:110`
- `apps/web/src/app/App.tsx:144`
- `apps/web/src/pages/AnalysesPage.tsx:36`
- `apps/web/src/pages/AnalysesPage.tsx:39`
- `apps/web/src/pages/AnalysesPage.tsx:40`
- `apps/web/src/pages/AnalysesPage.tsx:41`

问题说明：

- 后端 `/api/app/analyses` 默认 `page=1&pageSize=20`，并返回真实 `pagination.totalItems`。
- 前端 `api.listAnalyses()` 没有传分页参数，也没有加载其它页。
- `AnalysesPage` 的 `failedItems`、`waitingHumanItems`、`runningItems`、`completedCount`、复核队列等指标都只基于当前 `items`。
- 结果是任务总数来自全量 total，但运行失败/待人工/活跃运行/已完成等统计只来自第一页。

为什么重要：

- 当工作区超过 20 条分析后，首页指标会呈现“总数是真实全量，其它分类是第一页局部”的混合口径。
- 如果第一页都是成功任务，后面页存在失败/等待人工任务，运行时中心可能错误显示没有待处理事项。
- 这会削弱运行时中心作为治理入口的可信度。

建议方向：

- 后端增加按 status 聚合的 summary 字段，例如 `statusCounts`。
- 或前端明确只展示“当前页统计”，并提供分页/筛选加载。
- 运行时中心的活跃/失败/等待人工队列应使用 status filter 请求，而不是从第一页局部列表派生。

### Trajectory Log

| id | parent | score | evidence | decision | lesson |
| --- | --- | ---: | --- | --- | --- |
| T3-01 | root | 4/5 | auth/local scope/SessionGate 交叉证据明确 | keep | 配置语义需要和前端进入路径一起审计 |
| T3-02 | root | 4/5 | detail projection 与 download endpoint scope 校验不一致 | keep | app-facing 字段应表达已授权能力，不是内部可能性 |
| T3-03 | root | 5/5 | sidecar `os.chdir()` 是真实并发风险 | keep | 服务进程全局状态不能作为请求级隔离工具 |
| T3-04 | root | 4/5 | read-model RuntimeError 被 200 空列表吞掉 | keep | 治理页面不能把故障伪装成无数据 |
| T3-05 | root | 4/5 | `waiting_for_human` 有展示但无动作闭环 | keep | 终态不是 UI 标签，必须有可操作 lifecycle |
| T3-06 | root | 3/5 | dashboard 指标只来自第一页 | keep-low | 低成本修复，避免治理指标失真 |

### Next Experiment

最小可执行验证切片：

1. 为 `API_AUTH_REQUIRED=false + API_AUTH_TOKENS_JSON` 组合增加 session bootstrap 测试，决定 token store 是否仍应强制启用 auth。
2. 为越界 output 增加 detail-response 测试，要求 `downloadUrl is None`。
3. 为 `run_deerflow_sidecar.py` 增加相对 config path 解析单测，并移除请求级 `os.chdir()`。
4. 为 `AuditRepo.query_records()` failure 增加 app-facing 测试，要求返回 degraded/error，而不是空审计列表。
5. 为 `waiting_for_human` 设计一个最小 resume/cancel/归档合同。

---

## 补充审查四：CI/CD、Benchmark 与 QA 增量复核

补充日期：2026-04-27

### Scope

本节使用 `$ci-cd-and-automation`、`$benchmark`、`$qa` 的视角做增量审查，只补充当前 audit 未充分覆盖的问题。本节不修代码，也不重复“没有 CI / 没有统一 verify gate / 前端无自动化测试套件 / Docker gate 引用坏目标”等已有结论。

本轮实测：

- `cd apps/web && npm run lint`
  - 结果：通过
- `cd apps/web && npm run build`
  - 结果：通过
  - 构建摘要：JS `291.41 kB`，gzip `87.99 kB`；CSS `26.59 kB`，gzip `5.86 kB`

### 新增发现

#### 50. DeerFlow readiness smoke 默认不做真实 sidecar 调用，会给动态运行时假绿信号

严重级别：HIGH

证据：

- `docs/how-to/testing.md:42`
- `docs/how-to/testing.md:47`
- `docs/how-to/development.md:154`
- `docs/how-to/development.md:159`
- `scripts/smoke_deerflow_bridge.py:31`
- `scripts/smoke_deerflow_bridge.py:111`
- `scripts/smoke_deerflow_bridge.py:112`
- `scripts/smoke_deerflow_bridge.py:113`

问题说明：

- 测试文档把 `scripts/smoke_deerflow_bridge.py` 放在 readiness / smoke 命令里。
- 但脚本默认只验证模块 import、配置文件存在、`DeerFlowClient` 可构造。
- 只有显式传 `--run-chat` 时才会执行真实 chat 调用；默认路径输出 `chat SKIPPED` 后仍以 `READY FOR LIVE CHAT` 和 exit 0 结束。

为什么重要：

- 发布者会把“client 可构造”误读成“sidecar 可达、HTTP/streaming 正常、动态研究桥接可用”。
- 真实 sidecar 服务挂掉、网络不可达、chat/streaming 协议漂移时，当前默认 smoke 仍可能是绿的。
- 这会削弱第 46 条中 sidecar 并发风险之外的运行时发布信心：即便没有并发问题，live 链路也未被默认门禁验证。

建议方向：

- 把脚本拆成 `check-deerflow-config` 与 `smoke-deerflow-live` 两层。
- readiness 文档里的发布级命令默认应跑 live 版本，至少校验 sidecar `/health` 和一次最小 chat/stream 请求。
- 如果 live smoke 依赖密钥或外部服务，应显式区分 `skipped: missing credential`、`failed: sidecar unreachable`、`failed: protocol/runtime error`。

#### 51. app-facing “快速验收”脚本只验证创建接口，不能证明分析闭环可用

严重级别：MEDIUM

证据：

- `docs/how-to/deployment.md:211`
- `docs/how-to/deployment.md:215`
- `README.md:170`
- `README.md:173`
- `scripts/create_analysis.py:28`
- `scripts/create_analysis.py:29`
- `scripts/create_analysis.py:38`
- `scripts/create_analysis.py:39`

问题说明：

- 部署文档把 `scripts/create_analysis.py` 放在 “app-facing API 快速验收” 下。
- README 的“想跑起来并验证产品面”路径也会把用户导向部署与测试文档。
- 但脚本只发送一次 `POST /api/app/analyses`，收到成功响应后立即打印 JSON 并退出。
- 它不会轮询 `/events`，不会等待任务终态，不会读取分析详情，也不会验证输出产物下载。

为什么重要：

- 该脚本只能证明“创建请求被接受”，不能证明执行器、事件回放、summarizer、artifact projection、下载接口形成闭环。
- 分析创建后立刻失败、事件流坏掉、终态不更新或产物不可读时，这个“快速验收”仍可能通过。
- 对一个以“资料上传、任务路由、动态研究、代码执行、结果产物、审计回放”为闭环卖点的项目，create-only helper 不应被包装成产品面验收。

建议方向：

- 升级脚本为真正 happy-path smoke：创建分析后轮询详情/事件到终态，并至少读取一次输出列表或下载一个可读产物。
- 如果暂时不做闭环 smoke，应把文档标题改为“创建分析请求辅助脚本”，避免被纳入 release gate 时产生假信心。
- 将该脚本和浏览器 smoke 分层：API smoke 证明后端闭环，浏览器 smoke 证明前端能消费同一闭环。

#### 52. 前端依赖安装入口使用 `npm install`，没有利用 lockfile 的 CI 可复现语义

严重级别：MEDIUM

证据：

- `Makefile:18`
- `Makefile:19`
- `README.md:133`
- `README.md:137`
- `docs/how-to/deployment.md:98`
- `docs/how-to/deployment.md:102`
- `apps/web/package-lock.json:1`
- `apps/web/package-lock.json:4`

问题说明：

- 仓库已经提交 `apps/web/package-lock.json`，说明前端依赖应有锁定安装语义。
- 但 Makefile 的 `install-web` 和主要文档仍使用 `npm install`。
- `npm install` 可以在本地安装时更新或重解 lockfile；CI/release 更应该使用 `npm ci` 来保证严格按锁安装。

为什么重要：

- 当前前端 lint/build 已通过，但它证明的是“当前 node_modules + 当前 lockfile”组合可用，不证明新 runner 会以完全相同依赖树安装。
- 对多人协作和 CI 来说，依赖解析漂移会把“同一提交不同机器不同结果”的风险重新引入前端 gate。
- 这不是第 18 条 clean checkout 源码缺失问题，而是 lockfile 已存在但自动化入口未使用锁定安装语义的问题。

建议方向：

- 把文档与 Makefile 中的自动化安装入口统一改为 `npm ci`。
- 本地开发可以保留 `npm install` 说明，但 release/CI/verify 入口必须使用 `npm ci`。
- CI 增加 lockfile 漂移检查：运行安装和构建后，`git diff --exit-code apps/web/package-lock.json` 应保持干净。

#### 53. 模型 smoke 目标默认只做配置检查，目标命名会误导发布验证

严重级别：MEDIUM

证据：

- `Makefile:54`
- `Makefile:55`
- `docs/how-to/development.md:154`
- `docs/how-to/development.md:158`
- `scripts/smoke_dashscope_litellm.py:24`
- `scripts/smoke_dashscope_litellm.py:25`
- `scripts/smoke_dashscope_litellm.py:57`
- `scripts/smoke_dashscope_litellm.py:58`

问题说明：

- Makefile 暴露 `smoke-models`，开发文档也把 `scripts/smoke_dashscope_litellm.py` 放在关键 smoke / readiness 命令里。
- 但脚本默认 `live=False` 探测 alias/config，并且只有传 `--run-chat` 或 `--run-embedding` 时才会真实调用 provider。
- 默认无 live 参数时直接输出 `Result: CONFIG OK` 并返回 0。

为什么重要：

- `make smoke-models` 这个名字容易让维护者以为已经验证了 DashScope/LiteLLM chat 与 embedding 真链路。
- 实际上 provider 鉴权、网络、模型别名、embedding 维度、chat 返回格式都可能坏掉，而默认命令仍是绿的。
- 对 LLM 应用来说，模型链路 smoke 是核心运行时门禁；配置检查和 live 调用必须在命名和 exit 语义上分开。

建议方向：

- 将当前目标重命名为 `check-model-config`。
- 新增 `smoke-models-live`，显式传 `--run-chat --run-embedding`。
- live 目标应把缺少密钥标记为环境型 skip/不可验证，把真实调用失败标记为 release-blocking failure。

#### 54. Benchmark 基线默认落在被忽略目录，性能回归无法自然进入团队审查

严重级别：LOW

证据：

- `.gitignore:141`
- `apps/web/package.json:6`
- `apps/web/package.json:8`
- `apps/web/package.json:10`
- `docs/reference/project-status.md:22`
- `docs/reference/project-status.md:26`
- 本轮 `find .gstack -maxdepth 3 -type f -print` 未发现任何 benchmark baseline/report。
- 本轮 `npm run build` 只输出一次性 bundle 体积：JS `291.41 kB`，gzip `87.99 kB`；没有预算比较或趋势判断。

问题说明：

- gstack benchmark 的默认基线位置是 `.gstack/benchmark-reports/baselines/baseline.json`。
- 当前 `.gitignore` 忽略整个 `.gstack/`，因此即便本地采集了 benchmark baseline，也不会自然进入版本审查或团队共享。
- 前端脚本只有 `dev` / `build` / `preview` / `lint`，没有 bundle size budget、Lighthouse/Web Vitals、或 benchmark baseline compare。
- `project-status.md` 只记录一次人工浏览器 smoke 结果，没有性能指标、趋势或预算。

为什么重要：

- 构建通过并不等于性能没有退化。
- 当前 build 输出的 bundle size 是一次性日志，不会在 PR 中被比较，也不会形成历史趋势。
- 后续增加依赖、图表、预览、审计页面时，首屏 JS、接口瀑布、交互延迟可能逐步恶化，但没有 gate 会提示。

建议方向：

- 为前端建立可提交或可归档的 benchmark baseline，避免只放在被 ignore 的本地目录。
- 增加轻量预算：首屏 JS gzip、CSS gzip、关键页面接口数、首页/分析详情 LCP/TTI 或等价 smoke 指标。
- CI 中至少保留 `npm run build` 的 bundle 摘要 artifact；更理想是加一个 `benchmark:compare`，在超过预算或相对基线退化时失败。

### Trajectory Log

| id | parent | score | evidence | decision | lesson |
| --- | --- | ---: | --- | --- | --- |
| CQA-01 | root | 5/5 | DeerFlow smoke 默认 `--run-chat` 关闭且仍 exit 0 | keep | readiness 名字必须和真实验证深度一致 |
| CQA-02 | root | 4/5 | `create_analysis.py` 只 POST 创建，不轮询终态/事件/产物 | keep | 产品验收不能只验证入口接受请求 |
| CQA-03 | root | 4/5 | lockfile 已提交但入口仍使用 `npm install` | keep | CI/release 安装必须按锁执行 |
| CQA-04 | root | 4/5 | `smoke-models` 默认只做 config probe | keep | LLM config check 与 live smoke 要分离 |
| CQA-05 | root | 3/5 | `.gstack/` 被 ignore，benchmark 无基线/预算 | keep-low | 性能回归需要可共享基线而不是一次性 build 日志 |

### Next Experiment

最小整改切片：

1. 将 `scripts/smoke_deerflow_bridge.py` 和 `scripts/smoke_dashscope_litellm.py` 的 config-check / live-smoke 语义拆开，并重命名 Makefile 目标。
2. 扩展 `scripts/create_analysis.py`：创建任务后轮询事件和详情，直到 terminal status，并验证至少一个输出合同。
3. 将 release/CI 路径的前端安装命令统一为 `npm ci`。
4. 为 `apps/web` 增加 bundle budget 或 benchmark baseline compare，并决定 `.gstack/benchmark-reports` 是否应转存到可审查位置。


---

## 补充审查四：上传后业务文档未预解析，解析成本被推迟到分析 DAG（2026-04-28）

#### 55. 业务文档上传后没有后台预解析，导致用户创建分析时才集中等待

严重级别：MEDIUM

证据：

- `src/api/services/asset_service.py:256`
- `src/api/services/asset_service.py:264`
- `src/api/services/asset_service.py:271`
- `src/api/services/asset_service.py:471`
- `src/dag_engine/nodes/kag_retriever.py:64`
- `src/dag_engine/nodes/kag_retriever.py:78`
- `src/dag_engine/nodes/kag_retriever.py:91`
- `src/api/app_presenters.py:478`

问题说明：

- 用户上传 `business_document` 到资料库时，当前流程只把 workspace-level `KnowledgeData.business_documents` 同步为 `status="pending"`。
- 真正的文档解析 / KAG builder 入库发生在分析任务 DAG 流转到 `kag_retriever_node` 之后。
- 这意味着用户在“上传资料”阶段没有得到后台预处理收益，首次创建分析时才承担解析等待。
- 资料库 readiness 展示也因此只能粗略显示“待处理 / 可直接分析”，无法稳定表达 `processing / parsed / failed` 这类生命周期状态。

为什么重要：

- 业务文档解析是高延迟步骤，不应默认阻塞用户创建分析后的 DAG 主路径。
- 用户已经在资料库上传文件时，系统有机会提前完成解析、抽取和索引准备。
- 如果不做预解析，后续 routing / DAG 即使设计得更清楚，也仍会把“材料准备成本”推迟到用户等待分析结果的阶段。
- `kag_retriever` 应该是兜底 / 修复路径，而不是每份业务文档的正常首次解析入口。

根因：

- 上传服务只负责落盘和同步 asset metadata，没有触发后台知识构建任务。
- workspace asset 的解析状态没有形成清晰生命周期：`uploaded -> processing -> parsed | failed`。
- 创建分析时 attach workspace asset 只能重新构造 task-local `BusinessDocumentState`，没有可靠继承 workspace-level parse readiness。

建议方向：

- 在业务文档上传成功后触发后台预解析任务，异步调用现有 KAG builder / ingest pipeline。
- 将 workspace-level 文档状态持久化为 `uploaded / processing / parsed / failed`，并保存 parser diagnostics。
- 创建分析并 attach 已解析文档时，把 parsed 状态和 diagnostics 带入 task-local `ExecutionData.inputs.business_documents`。
- 保留 `kag_retriever` 的兜底职责：当文档仍 pending、解析失败、索引缺失或状态过期时，再在 DAG 中重试或阻断。
- 前端资料库 readiness 应区分处理中、可直接分析、解析失败，而不是只用“待处理”。

非目标：

- 本条不解决 routing 分类边界问题。
- 本条不重写 DAG。
- 本条不改变 `known_gaps`、`single_pass`、`iterative` 或 dynamic/static 分工。
- routing 问题应作为单独设计 / 实现任务处理，避免和上传预解析混成一个补丁。
