# lite-interpreter 面试叙事

## 1. 一句话定位

`lite-interpreter` 是一个“受控的数据智能 runtime”，不是一个自由发挥的 agent playground。

## 2. 为什么这个项目值得讲

面试时最值得讲的不是“我接了多少模型”，而是：

- 我把动态能力放进了一个有控制面的系统里
- 我把 agent 探索和本地代码执行做了明确边界
- 我让治理、状态、知识、执行结果都可以追踪

这比单纯“做了一个智能体”更有系统设计价值。

## 3. 推荐叙事主线

### 3.1 问题背景

很多 agent 系统的问题是：

- 规划和执行耦合
- 动态探索不可控
- 代码执行边界模糊
- 出问题后很难知道系统到底做了什么

### 3.2 我的核心决策

我没有把整个系统做成自由流 agent，而是拆成四层：

- 控制面
- 运行面
- 执行面
- 知识面

然后让：

- 稳定流程走 DAG
- 复杂探索走动态超级节点
- 最终代码执行始终留在本地 sandbox

### 3.3 关键设计亮点

#### 亮点 1：DAG 是 owner

动态能力不是系统主人，DAG 才是。

这意味着：

- Router 决定什么时候走动态链
- 动态链只是一个 bounded super node
- DeerFlow 只是 runtime backend

#### 亮点 2：Harness 进入关键路径

我没有把治理做成旁路配置，而是让它真的卡在关键路径上：

- 动态请求前先过 governance
- sandbox 执行前先过 governance
- allow/deny 决策会写回 blackboard，并投给前端

#### 亮点 3：执行边界清晰

动态链可以探索，但不能绕开本地 sandbox 执行代码。

这解决了很多 agent 系统里“谁来执行、在哪执行、能执行什么”的边界问题。

#### 亮点 4：状态与轨迹统一

我把关键状态统一成一组 contract：

- `TaskEnvelope`
- `ExecutionIntent`
- `DecisionRecord`
- `TraceEvent`
- `ExecutionRecord`

这样：

- blackboard 能存
- SSE 能发
- 前端能看
- 测试能断言
- 故障能追踪

#### 亮点 5：SkillNet 不只是技能清单

我没有停留在“把 prompt 存一下”，而是做了：

- capability-aware skill
- validation
- authorization
- promotion
- historical usage telemetry

这让动态探索的成功路径可以逐步沉淀成静态可复用能力。

## 4. 可以展开讲的模块

### Blackboard

可讲点：

- 为什么要把任务状态和执行状态分开
- 为什么要做 restore / persist
- 为什么动态 trace 和 governance decision 都要回写 blackboard

### Dynamic Runtime

可讲点：

- 为什么做 `DynamicSupervisor -> RuntimeGateway -> DeerflowBridge`
- 为什么留 `runtime_registry`
- 为什么推荐 sidecar，而不是把 DeerFlow 完全嵌入主进程

### Sandbox

可讲点：

- AST 审计 + harness + Docker 的三层边界
- session 化执行是为以后远程执行面做铺垫
- `ExecutionRecord` 让结果标准化，不再是随意 dict

### KAG

可讲点：

- 为什么选 LlamaIndex 作为 adapter，而不是让框架接管整个设计
- 为什么保留 layout-aware / parent-child / fallback chunking
- 为什么 query 返回 `EvidencePacket`，而不是只返回文档片段

## 5. 面试时怎么讲模块协作

推荐一句话版本：

“任务先进 API，Router 决定 static 还是 dynamic；治理策略先判断权限和风险；需要知识就走 KAG，需要执行就进 sandbox；所有状态、事件、trace 和结果都写回 blackboard，前端和 SSE 只是控制面的投影层。”

推荐展开版：

1. API 创建任务，并初始化 `ExecutionData`
2. Router 根据 query、数据、文档、历史技能做执行决策
3. 静态链走 inspector / retriever / analyst / coder / auditor / executor
4. 动态链走 supervisor / gateway / DeerFlow runtime
5. 无论静态还是动态，结果都进入 harvester 和 summarizer
6. 最终前端看到的不是零散日志，而是控制面整理后的统一任务视图

## 6. 现在这个项目处于什么阶段

可以诚实讲：

- 主链路已经打通
- 测试已覆盖到单测、编排测试和最小 e2e
- 更像一个高质量原型和架构验证环境
- 距离生产化还有工程化、部署化、环境 e2e 的工作

这比“全部都做完了”更可信。

## 7. 面试时不要讲偏的点

不建议重点讲：

- “我接了很多模型”
- “我也能做 agent”
- “这个系统可以全自动完成所有分析”

建议重点讲：

- 为什么要有控制面
- 为什么 agent 不能直接拥有执行权
- 为什么治理和状态模型要成为第一等公民
- 为什么技能沉淀要带 capability 和 validation

## 8. 一个稳妥的收尾说法

“这个项目最重要的不是某个单点算法，而是把动态探索、知识检索、本地执行和治理放进了同一个可控 runtime。它已经具备原型验证价值，下一步重点是继续把执行面拆细、补齐真实环境 e2e 和部署工程化。”
