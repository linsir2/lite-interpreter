# Execution Strategy Reference

`ExecutionStrategy` 是静态链新的内部主控制真相源。

它的职责不是替代 `AnalysisDetailResponse` 这样的 app-facing 合同，而是让下面这些内部判断不再散落在：

- `analysis_plan`
- `generation_directives`
- `next_static_steps`
- `dynamic_next_static_steps`
- renderer 自己的隐式约定

## 1. 当前 v1 字段

### `analysis_mode`

- 来源：`AnalysisBrief.analysis_mode`
- 作用：把 runtime 的业务分析模式投影到 generator 选择层

### `research_mode`

当前固定值：

- `none`
- `single_pass`
- `iterative`

作用：

- `none`：纯本地输入 + 确定性执行
- `single_pass`：允许一次受控外部取证，然后继续走静态链
- `iterative`：需要 DeerFlow 的多步探索/子 agent 编排

注意：

- 是否联网不再直接等于“必须走动态”
- router 只在 `research_mode=iterative` 时进入 DeerFlow

### `strategy_family`

当前固定值：

- `dataset_profile`
- `document_rule_audit`
- `hybrid_reconciliation`
- `input_gap_report`

### `generator_id`

- 作用：标记本次实际使用的 generator
- v1 约定：`<strategy_family>_generator`

### `artifact_plan`

- 作用：声明本次执行必须/可以产什么 artifact
- 主要消费者：
  - generator registry
  - executor 后的 artifact verification
  - summarizer / presenter 排序逻辑

### `evidence_plan`

- 作用：声明静态单次取证的范围与约束
- 主要字段：
  - `search_queries`
  - `urls`
  - `allowed_domains`
  - `allowed_capabilities`
- 当前只允许公开、只读、无认证来源
- 当前不允许把原生网络能力直接下放到沙箱

### `verification_plan`

- 作用：声明执行结束后要如何验证 artifact
- v1 主要规则：
  - required artifact 必须存在
  - artifact 必须在允许输出根目录下
  - `input_gap_report` 禁止图表后缀
  - 用户导向 artifact 必须属于声明过的文件名集合

### `program_spec`

- 类型：`StaticProgramSpec | null`
- 作用：coder 的主输入 IR
- 当前位置：始终走 `program_spec -> compiler`

### `repair_plan`

- 类型：`StaticRepairPlan | null`
- 作用：debugger 的单次修复指令
- 当前动作：
  - `simplify_program`
  - `drop_external_evidence`
  - `patch_evidence_plan`
  - `patch_artifact_plan`
  - `retry_with_evidence`

### `resume_overlay`

- 类型：`DynamicResumeOverlay | null`
- 作用：把动态链 -> 静态链 handoff 从 legacy metadata 中独立出来
- v1 仍然与 `next_static_steps` 双写

（注：`legacy_compatibility` 字段已删除。）

## 2. 当前落点

### 持久化

- `ExecutionData.static.execution_strategy`

### 技术投影

- `final_response.details.execution_strategy`
- `build_task_workspace_payload().workspace.technical_details.control/static/dynamic`

### 非落点

这些位置当前不应该直接扩张：

- `/api/app/*` 公共 schema
- `AnalysisDetailResponse`
- 前端本地状态 schema

## 3. 与其他字段的关系

### `analysis_plan`

- 继续保留
- 现在是展示辅助字段，不是主控制语义

### `GeneratorManifest`

- 记录“谁生成了什么 contract”
- 主要解决回放、审计、迁移 cutover 定位问题

### `ArtifactVerificationResult`

- 记录执行后 contract 是否满足
- 决定是否进入 debugger / fail 路径

### `StaticEvidenceBundle`

- 记录静态单次取证结果
- 当前存储在 `ExecutionData.static.static_evidence_bundle`
- 同时会落成一个只读 JSON 输入挂载给沙箱

## 4. v1 边界

- `ExecutionStrategy` 只收口静态链的策略与 artifact contract
- 不扩张 app-facing 公共合同
- 不把 DeerFlow 升格为 owner
- 不改变结构化输入支持范围声明
