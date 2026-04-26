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

#### 1. `analyst` 仍然是建议型规划器，而不是可执行规划器

严重级别：HIGH

证据：

- `src/dag_engine/nodes/analyst_node.py:122`
- `src/dag_engine/nodes/analyst_node.py:180`
- `src/dag_engine/dag_graph.py:105`
- `src/dag_engine/dag_graph.py:160`
- `src/dag_engine/dag_graph.py:187`

问题说明：

- `analyst` 当前主要产出的是自然语言形式的 `analysis_plan`
- DAG 真正执行的静态链结构仍然是硬编码的
- `coder` 之所以在 `analyst` 之后执行，核心原因仍然是图上写死了顺序，而不是 `analyst` 产出了一个任务特化的执行计划
- 真正的控制对象虽然已经开始向 `execution_strategy` 收敛，但它仍然主要由既有策略 helper 填充，而不是由 `analyst` 产出高表达力的计划合同后驱动整个 DAG

为什么重要：

- 系统表面上看起来“有规划”，但规划实际上没有被授予足够控制权
- DAG 行为仍然大部分由预设决定，而不是由任务理解决定
- 如果规划器输出仍然浅层，`coder` 就不可能真正根据任务意图变成任务自适应

根因：

- 当前缺少一个一等公民级别的 `AnalystPlan` 合同，去真正承载：
  - 必需节点
  - 可选节点
  - 联网策略
  - 产物预期
  - 验证标准
  - 升级到动态链的理由

建议方向：

- 把纯字符串规划升级为结构化计划合同
- 让 DAG 直接消费这份计划合同
- 让 `coder` 也消费同一份计划中的 codegen 意图与产物合同

#### 2. 静态代码生成仍然是模板驱动，不是真正按任务生成代码

严重级别：HIGH

证据：

- `src/dag_engine/nodes/coder_node.py:34`
- `src/dag_engine/nodes/static_codegen.py:37`
- `src/dag_engine/nodes/static_codegen_payload.py:243`
- `src/dag_engine/nodes/static_codegen_renderer.py:9`
- `src/dag_engine/nodes/static_generation_registry.py:482`

问题说明：

- `coder` 进入的几乎仍然是固定的 payload-builder + renderer 路径
- `static_codegen_payload` 虽然会派生 hints、terms、focus order，但并没有形成真正的“可执行推理计划”
- `static_codegen_renderer` 本质上仍然是一个巨大的字符串程序模板
- registry 的生成器选择仍然是 family 驱动，而不是真正的任务自适应 codegen

为什么重要：

- 代码形状仍然被预定义 scaffolding 主导
- 生成逻辑的变化幅度远小于任务变化幅度
- 当前系统更接近“参数化固定程序发射器”，而不是“面向任务目标生成分析代码”

根因：

- 架构把 payload enrichment 当成主要灵活性来源
- 真正的程序主体仍然存放在大块静态模板中

建议方向：

- 把 codegen 从模板主导切换到合同驱动的生成
- 保留安全护栏和 helper library
- 但分析主体逻辑要由 plan + schema + context 真正驱动生成

#### 3. 产物交付面仍被固定 family 和固定 emit 限死

严重级别：HIGH

证据：

- `src/dag_engine/nodes/static_generation_registry.py:102`
- `src/dag_engine/nodes/static_generation_registry.py:403`
- `src/dag_engine/nodes/static_generation_registry.py:482`

问题说明：

- 当前 artifact family 被预定义为：
  - `dataset_profile`
  - `document_rule_audit`
  - `hybrid_reconciliation`
  - `input_gap_report`
  - `legacy_dataset_aware_generator`
- 每个 family 对应的 artifact key 集合很小且固定
- emit kind 也是显式白名单，类型数量有限

为什么重要：

- 输出多样性从框架层就被封顶了
- 就算 codegen 做得更灵动，交付合同仍然限制了真正能暴露给前端 / 用户的内容
- 产物会长期维持在过少、过标准化的状态，无法支撑更丰富的分析任务

根因：

- 当前产物还是 registry 持有的固定输出，而不是规划器持有的任务特化交付物

建议方向：

- 建立更丰富的产物合同，例如：
  - 报告
  - 表格
  - 图表
  - 诊断产物
  - 中间导出物
  - 来源引用
  - 对账 / 归因轨迹
- 让 `analyst` 先为任务声明期望产物集合，再由 `coder` 按合同生成

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

#### 6. 动态链回流静态链后，仍然容易重新坍缩回模板 static codegen

严重级别：HIGH

证据：

- `src/dag_engine/dag_graph.py:366`
- `src/dag_engine/dag_graph.py:371`
- `src/dag_engine/dag_graph.py:420`

问题说明：

- dynamic research 完成后，知识和证据确实会被回流 Blackboard
- 但默认下一步仍然是重新走静态 briefing + 原来的 static codegen 路径
- 默认推荐文案里甚至直接指向“模板化执行代码”

为什么重要：

- dynamic research 的价值会在回流阶段被旧模板路径重新压平
- exploration 的收益无法真正升级下游 codegen 质量

根因：

- dynamic 当前只产 findings / trace / summary，但没有产出一个足够强的下游表示去改变 codegen 机制本身

建议方向：

- dynamic 回流不应只回填文本上下文
- 它应该回填：
  - 更强的计划合同
  - research bundle 对象
  - 更强的 codegen intent

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

#### 29. DAG 仍是硬编码流程脚本，不是 plan-driven DAG

严重级别：HIGH

证据：

- `src/dag_engine/dag_graph.py:19`
- `src/dag_engine/dag_graph.py:21`
- `src/dag_engine/dag_graph.py:113`
- `src/dag_engine/dag_graph.py:160`
- `src/dag_engine/dag_graph.py:187`
- `src/dag_engine/dag_graph.py:217`
- `src/dag_engine/dag_graph.py:233`

问题说明：

- `_next_actions()` 只允许 `executor/debugger/skill_harvester` 三类后继，说明大部分节点并不是由 plan/outcome 驱动，而是由 `_execute_static_flow()` 的代码顺序驱动
- `data_inspector -> kag_retriever -> context_builder -> analyst -> static_evidence? -> coder -> auditor -> debugger? -> executor -> debugger? -> skill_harvester -> summarizer` 被硬编码在一个函数里
- Analyst 产出的 `next_actions` 只能局部触发 `static_evidence`，无法声明拓扑、跳过节点、插入验证节点、声明并行分支或指定失败策略

为什么这是架构问题：

- “DAG” 没有一等的 graph spec / edge condition / node outcome，因此新增路径只能继续改 `dag_graph.py`
- 业务策略与控制流混在 imperative orchestration 里，导致 router/analyst/coder 的规划能力被架空
- 测试只能覆盖固定脚本路径，无法验证“某个 plan 应该生成某个拓扑”

建议方向：

- 引入显式 `WorkflowPlan` / `GraphPlan`：由 router/analyst 输出节点序列、edge condition、retry policy、terminal policy
- DAG executor 只解释 plan，不内置业务节点顺序
- 节点返回统一 `NodeOutcome`，由 orchestrator 根据 outcome 与 graph spec 决定下一步

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

#### 32. `ExecutionStrategy` 名义上是真相源，实际上 owner 被拆散

严重级别：HIGH

证据：

- `docs/reference/execution-strategy.md:3`
- `src/dag_engine/nodes/analyst_node.py:180`
- `src/dag_engine/nodes/static_generation_registry.py:482`
- `src/dag_engine/nodes/static_generation_registry.py:511`
- `src/dag_engine/nodes/static_generation_registry.py:517`
- `src/dag_engine/nodes/debugger_node.py:45`

问题说明：

- 文档声明 `ExecutionStrategy` 是静态链内部主控制真相源
- Analyst 先写入 analysis/research/evidence plan
- static generation registry 又基于输入数量、业务信号、existing payload 重新推导 `strategy_family` 与 artifact/verification plan
- Debugger 再根据失败把 repair action 写回，并可触发 `fallback_to_legacy`

为什么这是架构问题：

- “谁决定策略”没有唯一答案，导致 strategy 既像 plan，又像 generator registry 的派生结果，还像 debugger 的修复状态容器
- 新增 strategy family 时，需要同时理解 analyst、registry、debugger 三方覆盖规则
- 这会让 replay/debug 很难解释：某次 run 的 strategy 是规划出来的、推导出来的，还是修复时覆盖出来的

建议方向：

- 拆分为不可变 `StrategyPlan`、生成期 `GenerationBundle`、调试期 `RepairDecision`
- Analyst/Planner 只产 `StrategyPlan`
- Registry 只把 `StrategyPlan` 编译成 `GenerationBundle`，不得回写 plan owner 字段
- Debugger 只产 `RepairDecision`，不得直接重定义主策略归属

#### 33. Coder 不是清晰的代码生成边界，而是一次性写入 strategy/spec/artifact/verification 多个合同

严重级别：HIGH

证据：

- `src/dag_engine/nodes/coder_node.py:34`
- `src/dag_engine/nodes/coder_node.py:38`
- `src/dag_engine/nodes/coder_node.py:45`
- `src/dag_engine/nodes/static_codegen.py:15`
- `src/dag_engine/nodes/static_codegen.py:30`
- `src/dag_engine/nodes/static_codegen.py:67`
- `src/dag_engine/nodes/static_codegen.py:75`

问题说明：

- `coder_node` 调用 `prepare_static_codegen()` 后，同时写入 `generated_code`、`execution_strategy`、`static_evidence_bundle`、`program_spec`、`repair_plan`、`generator_manifest`、`artifact_plan`、`verification_plan`
- `PreparedStaticCodegen` 把代码、IR、artifact 合同、验证合同、manifest、repair plan 包成一个大返回对象
- coder 没有明确“输入 plan -> 输出 program IR -> 输出 code”的分层，也没有独立校验 program spec 是否满足 analyst plan

为什么这是架构问题：

- coder 变成“静态策略编译器 + artifact 合同生成器 + code renderer + verification plan author”
- 任何 artifact 合同或 verification 规则变化都要穿过 coder 路径
- debugger 复用 coder 后，repair 与正常 codegen 的边界进一步消失

建议方向：

- 拆成 `PlanCompiler`、`ProgramSpecValidator`、`CodeRenderer`、`ArtifactContractBuilder`
- coder 节点只负责从已冻结 plan/spec 生成 code bundle，并返回 typed `CodegenResult`
- artifact/verification plan 应由 plan/compiler 阶段生成并冻结，executor 只消费

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

#### 43. static codegen 存在“双后端 + 模板注入”架构债务，输出语义分散

严重级别：MEDIUM

证据：

- `src/dag_engine/nodes/static_generation_registry.py:475`
- `src/dag_engine/nodes/static_generation_registry.py:565`
- `src/dag_engine/nodes/static_generation_registry.py:568`
- `src/dag_engine/nodes/static_program_compiler.py:9`
- `src/dag_engine/nodes/static_program_compiler.py:440`
- `src/dag_engine/nodes/static_codegen_renderer.py:9`
- `src/dag_engine/nodes/static_codegen_renderer.py:40`

问题说明：

- legacy 路径走 `render_dataset_aware_code()`，再用 `_inject_artifact_writer()` 替换 final print 注入 artifact writer
- 非 legacy 路径走 `StaticProgramSpec -> compile_static_program()`，compiler template 里又定义一套输出/产物写入逻辑
- artifact plan、emit kind、verification、renderer/模板输出语义分散在 registry、compiler、renderer 三处

为什么这是架构问题：

- 新增 artifact type 或 computation step 时，可能要同时改 registry、compiler template、legacy renderer、verification、summarizer
- 字符串模板替换不是稳定接口，legacy adapter 难以证明与新 compiler 后端等价
- 代码生成器应该产 declarative spec，而不是在多个 Python 字符串模板里复制业务输出语义

建议方向：

- 收敛为统一 sandbox runtime helper/API：模板只调用 runtime helper，artifact 写入和 result schema 由 helper 保证
- generator 只产 `StaticProgramSpec + ArtifactPlan`
- legacy renderer 退化为 adapter，并用同一套 artifact emit API，不再通过字符串注入改写输出

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
