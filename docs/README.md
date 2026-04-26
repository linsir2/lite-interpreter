# 文档地图

`docs/` 现在按 **Diataxis** 的四种文档职责分层：

- `tutorials/`：带你从零跑通一条完整路径
- `how-to/`：告诉你具体任务怎么做
- `reference/`：给你当前系统的事实、基线和字典
- `explanation/`：解释为什么系统这样设计

如果你感觉以前的文档是“每份都讲一点，但没有一份能带路”，从这里开始读，不要再随机翻文件。

## 当前目录结构

```text
docs/
├── README.md
├── decisions/
│   ├── ADR-001-execution-strategy-ir.md
│   ├── ADR-002-artifact-generation-subsystem.md
│   └── ADR-003-legacy-static-contract-deprecation.md
├── tutorials/
│   └── first-analysis.md
├── how-to/
│   ├── deployment.md
│   ├── development.md
│   └── testing.md
├── reference/
│   ├── artifact-contracts.md
│   ├── execution-strategy.md
│   └── project-status.md
└── explanation/
    ├── architecture.md
    ├── from-internal-checks-to-user-deliverables.md
    └── legacy-removal-strategy.md
```

## 分层职责

### Tutorials

- `docs/tutorials/first-analysis.md`
  - 面向财务、会计、经营分析、业务复核人员
  - 目标：第一次把一条真实分析任务跑通

### How-to

- `docs/how-to/deployment.md`
  - 面向本地运行者、部署维护者
  - 目标：把 API、sidecar 和 Web 前端正确启动起来
- `docs/how-to/development.md`
  - 面向日常开发者
  - 目标：知道改动前看什么、改动后至少验证什么
- `docs/how-to/testing.md`
  - 面向开发者、QA
  - 目标：按改动类型挑对验证命令和测试层次

### Reference

- `docs/reference/project-status.md`
  - 面向所有人
  - 目标：查看当前状态、验证基线、已知热点和明确非目标
- `docs/reference/execution-strategy.md`
  - 面向改 DAG / runtime / summarizer 的开发者
  - 目标：查看 `ExecutionStrategy`、`GeneratorManifest`、`DynamicResumeOverlay` 的稳定字段和职责边界
- `docs/reference/artifact-contracts.md`
  - 面向改 generator / executor / presenter 的开发者
  - 目标：查看 family -> artifact contract 的固定映射和 v1 验证规则

### Explanation

- `docs/explanation/architecture.md`
  - 面向开发者、架构维护者
  - 目标：理解系统为什么这样分层、主链如何协作、边界在哪里
- `docs/explanation/from-internal-checks-to-user-deliverables.md`
  - 面向需要理解这轮重构的人
  - 目标：解释为什么 static chain 不再只输出内部 JSON，而要把 artifact 当作一等对象
- `docs/explanation/legacy-removal-strategy.md`
  - 面向后续迁移执行者
  - 目标：解释旧字段为什么不能立刻删除，以及 reader cutover 的顺序
- `项目二.md`
  - 面向需要理解工程判断的人
  - 目标：理解这轮收口做对了什么、还剩什么问题

### Decisions

- `docs/decisions/ADR-001-execution-strategy-ir.md`
  - 目标：记录 `ExecutionStrategy` 为什么成为内部主控制真相源
- `docs/decisions/ADR-002-artifact-generation-subsystem.md`
  - 目标：记录 artifact generation 为什么成为 static chain 的正式子系统
- `docs/decisions/ADR-003-legacy-static-contract-deprecation.md`
  - 目标：记录 `analysis_plan` / `generation_directives` / `next_static_steps` 等旧字段的迁移和删除门槛

### 补充入口

- `README.md`
  - 仓库入口页，负责“这是什么、怎么开始、接下来去哪读”
- `directory.txt`
  - 仓库目录导览，不承担实现解释

## 推荐阅读路径

### 路径 A：第一次接手仓库

1. `README.md`
2. `docs/reference/project-status.md`
3. `docs/explanation/architecture.md`
4. `directory.txt`
5. `docs/how-to/development.md`

### 路径 B：我要把系统跑起来

1. `README.md`
2. `docs/tutorials/first-analysis.md`
3. `docs/how-to/deployment.md`
4. `docs/how-to/testing.md`
5. `scripts/create_analysis.py`

### 路径 C：我是业务同学，只想把一次分析跑通

1. `docs/tutorials/first-analysis.md`
2. `README.md`
3. 找管理员要 API 地址和 Bearer Token
4. 先在 Web 前端完成一次小范围分析

### 路径 D：我要改前端或 app-facing API

1. `docs/reference/project-status.md`
2. `docs/explanation/architecture.md`
3. `docs/how-to/development.md`
4. `apps/web/src/lib/api.ts`
5. `src/api/routers/app_router.py`
6. `src/api/app_schemas.py`

### 路径 E：我要查当前系统还能不能信

1. `docs/reference/project-status.md`
2. `docs/how-to/testing.md`
3. `tests/test_api_route_surface.py`
4. `tests/test_api_app.py`
5. `tests/test_docs_consistency.py`

## 文档维护规则

为了避免文档再次漂移，仓库文档按下面的职责维护：

- `docs/reference/project-status.md` 是“状态与基线”的唯一真相源
- `README.md` 只做入口，不记录会快速过期的细节表
- `docs/explanation/architecture.md` 只解释结构与边界，不重复部署命令
- `docs/how-to/deployment.md` 只讲运行与配置，不重复架构讨论
- `docs/how-to/development.md` 只讲开发流程和入口
- `docs/how-to/testing.md` 只讲验证方法，不维护项目叙事
- `docs/tutorials/first-analysis.md` 只讲业务用户操作路径
- `directory.txt` 只描述目录和入口，不承担实现细节解释

## 当前缺口

当前仓库仍缺一份真正带截图的产品 onboarding。如果后面要补，继续放在 `tutorials/`，不要把它塞回 how-to 或 explanation 文档里。
