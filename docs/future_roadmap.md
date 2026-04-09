# lite-interpreter 未来展望

## 1. 当前完成度

截至当前版本，`lite-interpreter` 已经完成以下核心能力：

- 静态链和动态链的统一编排
- 单一 `ExecutionEvent` 事件模型
- 本地 sandbox 执行边界与 AST 审计
- DeerFlow dynamic runtime 接入
- KAG 检索与上下文拼装
- SkillNet 技能沉淀与预置技能种子
- Execution / artifacts / tool-calls 资源层
- diagnostics / conformance / runtime capability manifest
- 单机多进程语义下的 task lease / claim / heartbeat / release
- 隐私脱敏 hooks
- 上传、知识资产页、技能页、任务台

当前验证基线与成熟度分层统一记录在 `docs/project_status.md`，本文件只讨论后续路线，不再单独维护测试结果数字。

## 2. 近期路线图

### 2.1 控制面增强

- 增加独立的 task lease / worker 状态查询 API
- 在前端增加 lease/worker 可视化页，而不仅仅嵌入在 diagnostics 和 task result 中
- 将 startup recovery 的状态从当前的进程内统计扩展为更完整的恢复历史记录

### 2.2 执行面增强

- 继续拆分 `sandbox/docker_executor.py`
- 增加更细的容器阶段事件：
  - image check
  - mount preparation
  - container start
  - log collection
  - cleanup
- 增加 artifact metadata 扫描，而不仅仅返回目录路径

### 2.3 任务状态机增强

- 把当前 task status 从“节点驱动状态更新”进一步收口为显式状态机
- 定义：
  - allowed transitions
  - retry semantics
  - recoverable / terminal / blocked 分类
- 为 startup recovery、lease timeout、人工介入提供更清晰的状态边界

## 3. 中期路线图

### 3.1 单机分布式协调强化

虽然当前项目不计划做多机器分布式，但在单机多进程场景下仍可继续增强：

- 更完整的 worker lease 模型
- heartbeat timeout 后的接管策略
- worker owner 的详细 metadata
- lease owner 的可视化和管理接口
- 手动释放僵尸 lease 的运维接口

### 3.2 更真实的长链验收

- 增加面向真实文件的 smoke 数据集
- 增加：
  - 上传结构化数据
  - 上传业务文档
  - KAG 入库
  - 静态链执行
  - 动态链执行
  - sandbox 产物生成
  - 技能沉淀
  的整链验收脚本

### 3.3 观测与诊断增强

- diagnostics 增加更细粒度的探针：
  - Docker image readiness
  - Qdrant collection 状态
  - Neo4j APOC 能力
  - Postgres lease table readiness
  - DeerFlow sidecar stream health
- 增加 execution runtime metadata 的前端展示

## 4. 长期路线图

### 4.1 多节点扩展准备

如果未来需要从单机多进程扩展到多节点：

- task lease 机制可以继续沿用
- 需要新增的主要不是 DAG 或 KAG 逻辑，而是：
  - 共享文件存储或对象存储
  - 更强的 worker registry
  - 多节点 recovery 去重
  - 更严格的 heartbeat / fencing token 机制

也就是说，当前架构已经具备向多节点演进的基础，但当前项目不以此为短期目标。

### 4.2 产品化方向

- 更强的工作台界面
- 任务历史与回放页
- 技能管理与审批页
- 执行资源浏览器
- 面向运维的系统健康页

## 5. 不建议当前立刻做的事

为了保持项目整洁，以下事项当前不建议立刻推进：

- 引入新的编排框架替换现有 DAG 设计
- 把 DeerFlow 提升为系统 owner
- 把 sandbox 改成远程独立服务
- 在没有真实运维需求前过早引入 Redis、消息队列、复杂分布式组件
- 为“未来可能多机”而提前重写当前单机可用实现

## 6. 结论

当前 `lite-interpreter` 已经从“设计原型”走到了“单机可用、单机多进程可协调、具备完整主链和基础运维可见性”的阶段。

后续演进应遵循同一个原则：

- 优先增强现有边界
- 优先补强可观测性和验收
- 避免再引入平行体系
- 保持静态链、动态链、sandbox、harness、KAG、SkillNet 的原始设计思路稳定
