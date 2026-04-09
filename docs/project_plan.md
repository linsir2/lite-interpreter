# lite-interpreter 项目计划书

## 1. 项目定位

`lite-interpreter` 的目标不是做一个完全自由发挥的 autonomous agent，而是做一个可控、可观测、可审计、可回放的企业级数据智能执行平台。

当前架构已经形成了一个较清晰的四层模型：

- 控制面：Blackboard、Event Bus、Event Journal、SSE
- 运行面：DAG 静态链 + DeerFlow 动态超级节点
- 执行面：本地 Sandbox、AST 审计、Execution Record
- 知识面：KAG、MCP Gateway、SkillNet、历史技能复用

## 2. 当前项目状态结论

### 2.1 已完成能力

- 已形成从 API 创建任务到静态链/动态链执行、总结回复、技能回收的最小闭环
- 已形成 `TaskEnvelope / ExecutionIntent / DecisionRecord / ExecutionRecord` 这一组跨模块共享契约
- 已形成 `DynamicSupervisor -> RuntimeGateway -> DeerflowBridge` 的动态执行分层
- 已形成 `HarnessGovernor -> SandboxExecTool -> Docker Executor` 的执行治理边界
- 已形成 `KAG Builder -> QueryEngine -> ContextBuilder` 的知识链路
- 已形成 `SkillHarvester -> SkillPromoter -> MemoryRepo` 的技能沉淀链路
- 已形成 `RuntimeCapabilityManifest` + runtime capability API
- 已形成单一 `ExecutionEvent` 事件层
- 已形成 execution / artifacts / tool-calls 资源层
- 已形成 diagnostics / conformance API
- 前端 `task_console` 已开始消费 executions / tool-calls API
- 已形成 execution attach/resume stream，并已接入前端 execution 优先流式视图
- 已补齐静态链 synthetic `knowledge_query` / `sandbox_exec` tool-call 资源

### 2.2 当前验证状态

- 最新验证命令与结果以 `docs/project_status.md` 为准。
- 本文件只保留实现结论、问题分解与改造计划，不再复制测试基线数字。

说明：

- 主链路原型是可运行的
- 现阶段问题主要不是“跑不起来”，而是“控制面一致性、持久化完整性、事件流关闭语义、工程化配置和真实 e2e 深度还不够”

## 3. 模块协作关系

### 3.1 主链路协作

任务主链路当前可概括为：

1. `api/routers/analysis_router.py`
   创建任务、初始化 `ExecutionData`、触发后台任务流
2. `dag_engine/nodes/router_node.py`
   根据 query、结构化数据、业务文档、历史技能决定走静态链还是动态链
3. 静态链
   `data_inspector -> kag_retriever -> context_builder -> analyst -> coder -> auditor -> executor -> skill_harvester -> summarizer`
4. 动态链
   `dynamic_swarm -> skill_harvester -> summarizer`
5. `blackboard/*`
   承担任务状态、执行状态和知识状态的跨节点共享
6. `common/event_bus.py` + `common/event_journal.py`
   将状态变化投射到前端和回放链路

### 3.2 动态链协作

动态链当前分工是合理的：

- `DynamicSupervisor` 负责任务信封、执行意图、治理决策、上下文封装
- `RuntimeGateway` 负责运行时后端选择
- `runtime_registry` 负责后端扩展点
- `DeerflowBridge` 负责 embedded/sidecar/auto 三种运行模式
- `TraceNormalizer` 负责事件格式统一

这是当前项目中分层最清晰的一块。

### 3.3 Harness 协作

Harness 当前位于真正的关键路径上，而不是旁路装饰：

- 动态链进入前，会经过 `HarnessGovernor.evaluate_dynamic_request`
- Sandbox 执行前，会经过 `HarnessGovernor.evaluate_sandbox_execution`
- 治理结果会写回 `ExecutionData`，也会通过 SSE 推送给前端

这说明 harness 在设计上已经不是“开关配置”，而是控制面的一部分。

## 4. 模块内部实现评估

### 4.1 做得好的地方

- `common/contracts.py` 把跨模块共享模型收敛到了一个地方，后续演进成本可控
- `mcp_gateway/tools/state_sync_tool.py` 让 DAG 节点和动态节点不直接耦合 Blackboard 内部实现
- `kag/retriever/query_engine.py` 已经开始输出 evidence-aware 结果，不再只是 hit list
- `skillnet` 已经从“存技能描述”走向“授权、验证、提升、回放、统计反馈”
- `sandbox/session_manager.py` 给未来远程化执行面预留了 session seam

### 4.2 当前工程弱点

- `dag_engine/nodes/coder_node.py` 已经做了一轮 helper 拆分，但节点内部仍承载较多技能融合与黑板回写逻辑
- `sandbox/docker_executor.py` 已经抽出了 execution reporting，但容器生命周期、并发控制、清理逻辑仍然偏集中
- 工程配置已补到 `pyproject.toml`，但还没有把 lint/typecheck 统一进 Makefile/CI
- `tests/test_e2e.py` 已补齐最小 static/dynamic e2e，但进程重启恢复、多租户并发、真实 sidecar 链路仍缺少更强验收
- execution / tool-call 资源目前仍是从 blackboard 派生，尚未演进到独立生命周期对象
- diagnostics / conformance 已有最小实现，但还没有接真实 sidecar / Docker / 外部依赖的细粒度探针

## 5. 并发与状态同步评估

### 5.1 当前并发实现

项目当前有三类显式并发：

- `common/event_bus.py`
  使用后台线程 + asyncio loop + queue 做事件分发
- `sandbox/docker_executor.py`
  使用全局锁、租户并发计数和 `ThreadPoolExecutor`
- `kag/builder/parallel_ingestor.py`
  使用 `ThreadPoolExecutor` 并行解析文档

### 5.2 当前并发设计优点

- 并发热点都集中在基础设施层，而不是撒在业务节点里
- Sandbox 有显式的租户级并发上限
- Event Journal 给 SSE 提供了回放能力，降低了纯实时订阅的脆弱性

### 5.3 当前并发设计隐患

1. `common/event_bus.py`
   `stop()` 只改 `_running=False`，没有停止 loop、等待队列 drain、join 后台线程，关闭语义不完整。
2. `common/event_bus.py`
   `_process_events()` 在真正分发完成前就 `task_done()`，也没有对派生 task 做收敛，事件风暴下可能出现未完成任务堆积。
3. `blackboard/global_blackboard.py`
   全局任务状态只在内存里，和 `event_journal` / `execution_blackboard` 的“可恢复”设计不一致，进程重启后控制面状态会丢。
4. `data_inspector.py`
   成功更新了 `structured_datasets[*].schema/load_kwargs`，但成功路径没有立刻 `write/persist`，耐久性依赖后续节点再次写回。

## 6. 当前确定需要修改的点

以下按“已完成”和“下一步重点”区分。

### 已完成

1. Global Blackboard 持久化与恢复
   已完成：
   `GlobalBlackboard` 已接入 `StateRepo`，支持按 `task_id` 恢复与列出未完成任务。

2. 静态链终态写入收敛
   已完成：
   静态链最终 `SUCCESS/FAILED` 统一由 `analysis_router` 在总结后写入一次。

3. Event Bus 关闭/分发语义收紧
   已完成：
   `event_bus` 已等待事件分发完成后再 `task_done`，并补了 `stop(timeout=...)`。

4. `data_inspector` 成功路径持久化
   已完成：
   schema / load_kwargs 在成功探查后立即 `write/persist`。

5. 工程配置与最小 e2e
   已完成：
   `pyproject.toml` 已补齐，`tests/test_e2e.py` 已补上最小 static/dynamic 验收测试。

6. OpenHarness 思想的第一阶段吸收
   已完成：
   runtime capability manifest、execution event v2、execution resource layer、tool-call resource layer、diagnostics/conformance、runtime support matrix、execution attach/resume stream 已落地。

### 下一步重点

1. 继续拆分 `coder_node.py`
   当前状态：
   已拆出 payload / template helper，下一步建议继续收缩技能融合与状态写回逻辑。
   目标边界：
   - code payload builder
   - dataset profiling helpers
   - rule/metric/filter evaluation helpers
   - code template renderer

2. 继续拆分 `docker_executor.py`
   当前状态：
   已拆出 result/session/event projection，下一步建议继续拆资源清理和并发控制。
   目标边界：
   - docker client lifecycle
   - concurrency guard
   - sandbox session binding
   - execution runner
   - artifact/governance event projection

3. 深化工程化配置
   当前状态：
   `pyproject.toml` 已补全。
   剩余工作：
   - 接入统一 lint/type/test 命令
   - 统一本地/CI 入口

4. 深化真实 e2e
   当前状态：
   已补齐最小 static/dynamic e2e。
   剩余工作建议：
   - 进程重启后的状态恢复
   - 真实 sidecar / Docker / 外部依赖的环境验收
   - 多租户/并发场景验收

5. 继续完善资源化执行面
   当前状态：
   execution / artifacts / tool-calls 已能通过 API 查询。
   剩余工作：
   - 更细粒度 execution diagnostics
   - execution stream 在前端的更完整交互体验（切换 execution、过滤事件、断点恢复提示）

## 7. 分阶段改造计划

### 阶段 0：控制面一致性修补

目标：

- 消除重复终态事件
- 补齐任务状态持久化和恢复
- 让控制面与执行面拥有统一恢复语义

交付：

- `GlobalBlackboard` 增加 save/restore 能力
- `analysis_router` 去掉重复终态写入
- 增加对应回归测试

### 阶段 1：状态同步与事件流加固

目标：

- 让 Blackboard patch 语义更稳定
- 让 Event Bus 在高频/关闭场景下更可控

交付：

- Event Bus 关闭流程重构
- event queue drain/join 语义补齐
- SSE backlog/reconnect 压测用例

### 阶段 2：静态链可维护性重构

目标：

- 让静态链从“原型可用”升级到“工程上可维护”

交付：

- 拆分 `coder_node.py`
- 抽离 dataset profile、rule check、summary renderer
- 建立更细粒度单测

### 阶段 3：执行面与 Harness 强化

目标：

- 让 sandbox/harness 不只是能跑，而是便于扩展成生产级执行平面

交付：

- 拆分 `docker_executor.py`
- session、artifact、governance、event projection 分层
- 增加更多基于 task/workspace 的执行审计字段

### 阶段 4：知识面与动态链深化

目标：

- 把 KAG、SkillNet、动态链从“可串起来”推进到“可持续优化”

交付：

- 补齐真实 Dynamic Runtime e2e
- 增强 Skill effectiveness feedback
- 强化 KAG parser reports、retrieval budget、query rewrite 观测指标

## 8. 建议的验收标准

### 架构验收

- 控制面状态在进程重启后可恢复
- 终态事件只发送一次
- 动态链和静态链都能输出统一 final response

### Harness 验收

- 动态请求和沙箱执行都必须先过治理
- allow/deny 决策可在 Blackboard、SSE、最终响应中追溯

### 并发验收

- 多 SSE 订阅下无事件泄漏
- Event Bus 关闭时可干净退出
- 单租户并发上限生效

### 工程验收

- `pyproject.toml` 完整
- 存在真实 e2e
- CI 至少包含 lint/test

## 9. 我对项目的总体判断

这是一个“架构方向是对的、主链已经打通、但距离生产化还有一轮控制面和工程化收口”的项目。

最值得保留的设计是：

- DAG 仍然是系统 owner
- DeerFlow 被定位成受控 runtime，而不是系统主人
- Harness 已经进入关键路径
- Blackboard + Event Journal + SkillNet 的组合具备长期演化价值

最需要优先收口的部分是：

- 控制面耐久性
- 事件一致性
- 静态链实现体积
- 工程化配置与真实 e2e

如果按本计划推进，我建议优先顺序固定为：

1. 控制面一致性
2. 事件与并发收口
3. 静态链重构
4. 执行面重构
5. 动态链和知识面的深水区优化
