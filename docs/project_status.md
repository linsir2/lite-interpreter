# lite-interpreter 当前状态

## 1. 一句话定位

`lite-interpreter` 当前是一个面向数据分析任务的、受控且可观测的 agent runtime 原型，不是一个以“自由发挥”为目标的通用 autonomous agent 产品。

## 2. 最新验证基线

- 最后人工验证日期：`2026-04-20`
- 验证命令：`conda run -n lite_interpreter python -m pytest -q`
- 最新结果：`298 passed, 5 skipped`
- 说明：当前基线在本机环境下通过；5 个 skip 来自 Docker / 本地 TCP 绑定等环境能力缺失，而不是已知断言失败。

这份文档是仓库内关于“当前成熟度、测试基线、已知热点、非目标”的唯一真相源。其它文档只引用这里，不再各自维护测试通过数字。

## 3. 当前成熟度分层

### Core

这些部分直接证明主闭环成立：

- DAG 静态链与 DeerFlow 动态超级节点
- Blackboard / Event Bus / Event Journal 控制面
- Harness 治理与本地 Sandbox 执行边界
- API / app-facing analyses / polling stream 主链路
- Web Analyses 主工作台

### Support

这些部分明显增强主闭环，但不是判断闭环是否成立的唯一标准：

- KAG 检索与上下文拼装
- SkillNet 沉淀、授权、历史复用
- diagnostics / conformance / runtime capability manifest
- deterministic evals 与分析运行时分类

### Experimental

这些部分仍然是外围能力，不应包装成版本核心承诺：

- `Assets / Methods / Audit` 等辅助页面
- 更完整的 artifact 内容 API 与下载体验
- 更强的多文件上传与 workspace 资产编排体验

## 4. 当前最重要的已知热点

1. `src/sandbox/docker_executor.py` 仍然偏大，后续应继续拆容器生命周期、并发控制、结果映射。
2. `src/dag_engine/nodes/static_codegen.py` 仍然偏模板化，后续应让 `analysis_plan` 和 skill hints 更深地影响代码生成策略。
3. artifact 目前已做路径安全收口，但前端还缺完整的受控内容读取 API。
4. workspace 资产到 task 输入的“显式挂接”产品流仍未完全做完。
5. skill usage / outcome 在跨进程并发场景下仍需进一步做原子化持久化。

## 5. 当前明确非目标

- 不把 DeerFlow 提升为系统 owner
- 不把 Sandbox 改造成远程独立执行服务
- 不恢复 embedded / auto runtime mode
- 不继续宣传未完成闭环的结构化格式支持
- 不把外围辅助页面包装成当前版本核心交付
