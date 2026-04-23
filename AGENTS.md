# AGENTS.md - lite-interpreter 仓库协作约束

本文件是 `lite-interpreter` 仓库根目录下的协作契约，适用于整个仓库。

它不再承担历史知识库或长期路线图的职责；那些内容统一放到：

- `README.md`
- `docs/README.md`
- `docs/reference/project-status.md`
- `docs/explanation/architecture.md`
- `项目二.md`

## 1. 项目当前定位

`lite-interpreter` 当前是一个面向财务、会计与经营分析场景的、受控且可观测的分析运行时原型。

当前真实产品面已经收口为：

- 真实 Web 前端：`apps/web`
- app-facing API：`/api/app/*`

不要再把仓库理解为：

- 已废弃产品面的临时原型
- 旧 `tasks / executions / uploads` 产品接口集合
- 多种动态 runtime 模式并存的实验场

## 2. 当前必须尊重的边界

### 产品面边界

- 前端主工作台在 `apps/web`
- 产品前端只应消费 `/api/app/*`
- 不要恢复旧公开产品接口给前端使用
- 不要重新引入已废弃前端或相关默认值

### 编排与执行边界

- DAG 仍是主流程 owner
- DeerFlow 只负责受控动态研究，不是系统 owner
- 最终代码执行边界仍在本地 sandbox
- Blackboard 是状态事实源，不要绕开它传隐式状态

### 输入边界

当前静态链可靠支持的结构化输入格式是：

- `csv`
- `tsv`
- `json`

不要继续把 `xlsx / xls / parquet` 当成“稳定支持”写进产品文案或开发说明。

## 3. 关键目录

### 产品前端

- `apps/web/src/app/App.tsx`
- `apps/web/src/app/AppShell.tsx`
- `apps/web/src/lib/api.ts`
- `apps/web/src/lib/types.ts`
- `apps/web/src/pages/*`

### app-facing API

- `src/api/main.py`
- `src/api/routers/app_router.py`
- `src/api/app_schemas.py`
- `src/api/app_presenters.py`
- `src/api/services/task_flow_service.py`
- `src/api/services/asset_service.py`

### 核心运行时

- `src/blackboard/*`
- `src/dag_engine/*`
- `src/dynamic_engine/*`
- `src/sandbox/*`
- `src/kag/*`
- `src/skillnet/*`

## 4. 文档真相源

改动仓库时，优先遵守下面的文档职责：

- `docs/reference/project-status.md`：当前状态、测试基线、热点、非目标的唯一真相源
- `README.md`：仓库入口，不维护大量易过期细节
- `docs/explanation/architecture.md`：只解释结构与边界
- `docs/how-to/deployment.md`：只讲运行、配置、排障
- `docs/how-to/development.md`：只讲改动流程与开发入口
- `docs/how-to/testing.md`：只讲验证方法与测试分层
- `docs/tutorials/first-analysis.md`：只讲业务用户操作路径
- `directory.txt`：只做目录导览

## 5. 高风险漂移点

以下改动如果发生，必须同步更新文档与契约：

1. 产品前端页面结构或主导航改变
2. `/api/app/*` 字段、路径、行为改变
3. 本地联调端口、CORS 默认值、认证方式改变
4. 资料上传、`assetIds` 挂接、结果产物读取方式改变
5. 动态运行时支持范围改变

至少同步检查这些文件：

- `README.md`
- `docs/README.md`
- `docs/how-to/deployment.md`
- `docs/how-to/development.md`
- `docs/how-to/testing.md`
- `directory.txt`
- `.env.example`
- `config/settings.py`

## 6. 改动建议

### 改前端时

- 同步检查 `apps/web/src/lib/types.ts` 与 `src/api/app_schemas.py`
- 同步检查 `apps/web/src/lib/api.ts` 与 `src/api/routers/app_router.py`
- 不要引入第二套状态真相

### 改 app-facing API 时

- 优先改 schema / presenter / route / frontend consumer 四件套
- 旧产品面路由不要悄悄“顺手恢复”
- 涉及产品合同变化时，同步改文档和测试

### 改配置时

- `.env.example`
- `config/settings.py`
- `docs/how-to/deployment.md`

这三处应当一起改

## 7. 最低验证要求

### 文档或配置改动

```bash
cd /home/linsir365/projects/lite-interpreter
conda run -n lite_interpreter python -m pytest -q tests/test_docs_consistency.py
```

### 前端改动

```bash
cd /home/linsir365/projects/lite-interpreter/apps/web
npm run lint
npm run build
```

### 后端或合同改动

```bash
cd /home/linsir365/projects/lite-interpreter
conda run -n lite_interpreter python -m pytest -q
```

## 8. 最后提醒

当前仓库最忌讳的不是“功能少”，而是重新出现两套真相：

- 一套写在代码里
- 一套写在旧文档里

如果你改了产品面、接口面、配置面，却没有同步文档和测试，这个仓库会很快再次失真。
