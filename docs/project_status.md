# lite-interpreter 当前状态

## 1. 一句话定位

`lite-interpreter` 当前是一个面向数据分析任务的、受控且可观测的 agent runtime 原型，不是一个以“自由发挥”为目标的通用 autonomous agent 产品。

## 2. 最新验证基线

- 最后人工验证日期：`2026-04-09`
- 验证命令：`conda run -n lite_interpreter python -m pytest -q`
- 最新结果：`267 passed`
- 说明：该最强基线包含可访问本地 Docker daemon 与本地 TCP 绑定能力下的真实 sandbox / sidecar 传输验证；快速复验命令为 `make test-integration`

这份文档是仓库内关于“当前成熟度、测试基线、已知热点、非目标”的唯一真相源；`README.md`、`docs/project_plan.md`、`docs/future_roadmap.md` 只引用此处，不再各自维护单独版本。

## 3. 当前成熟度分层

### Core

这些部分直接证明主闭环成立，属于当前版本的核心能力：

- DAG 静态链与 DeerFlow 动态超级节点
- Blackboard / Event Bus / Event Journal 控制面
- Harness 治理与本地 Sandbox 执行边界
- API / SSE 主链路
- Task Console 主工作台

### Support

这些部分显著增强主闭环，但不是判断闭环是否成立的唯一标准：

- KAG 检索与上下文拼装
- SkillNet 沉淀、授权、历史复用
- execution / artifacts / tool-calls / diagnostics / conformance 资源层
- deterministic evals 与分析运行时分类

### Experimental

这些部分可以继续探索，但当前不应被当成“版本核心承诺”：

- `knowledge_manager` / `skill_manager` 等外围管理页
- 更重的产品化工作台外壳
- 尚未证明能显著提升主链成功率的扩展能力

## 4. 当前最重要的已知热点

- `src/sandbox/docker_executor.py` 仍然承担较多执行前置、容器编排、失败映射与清理职责，需要继续压缩到更清晰的内部 seam。
- 静态链代码生成路径已经拆出 `static_codegen.py`，但仍需继续把 skill recall / payload 装配等复杂度留在 helper 层，而不是回流到 `coder_node.py`。
- 文档必须继续围绕本页同步，避免再次出现多个文档分别维护不同测试基线和成熟度叙事。
- repo 仍存在较大的历史 lint / format 债；当前 `make lint` / `make fmt-check` 先锁住热点文件，`make lint-all` / `make fmt-check-all` 用于显式查看全仓范围债务。

## 5. 当前明确非目标

- 不把 DeerFlow 提升为系统 owner
- 不把 Sandbox 改造成远程独立执行服务
- 不为了“未来可能多节点”提前引入复杂分布式基础设施
- 不把实验性页面和外围管理能力包装成当前版本的核心交付
