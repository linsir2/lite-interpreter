# lite-interpreter

`lite-interpreter` 是一个面向财务、会计与经营分析场景的受控分析运行时。

它把“资料上传、任务路由、动态研究、代码执行、结果产物、审计回放”放进同一条工程闭环里：前端是一个真正的 React/Vite Web 工作台，后端暴露稳定的 `/api/app/*` app-facing 合同，底层继续由 DAG、Blackboard、Sandbox、KAG、SkillNet 和 DeerFlow sidecar 协同完成分析任务。

当前成熟度、测试基线、已知热点统一以 `docs/reference/project-status.md` 为准；本文件负责回答“这个项目是什么、现在怎么跑、接下来该看哪份文档”。

## 这是什么 / 不是什么

### 这是

- 一个面向数据分析任务的工程化运行时，而不是自由发挥的通用 autonomous agent
- 一个以“可治理、可观测、可回放、可交付”为目标的分析平台原型
- 一个已经完成前端硬切换的产品面：真实 Web 前端 + app-facing API

### 这不是

- 不是把所有事情塞进一个 prompt 的黑箱助手
- 不是把 DeerFlow 当系统 owner 的 runtime playground
- 不是宣称支持很多格式、但实际链路闭不了环的“假支持”产品

## 当前交付面

当前仓库真正对外的产品面已经收口到以下几部分：

### Web 前端

- 目录：`apps/web`
- 技术栈：React 18、TypeScript、Vite、React Router、TanStack Query、Tailwind CSS
- 主要页面：
  - `Analyses`：分析总览
  - `New Analysis`：新建分析
  - `Analysis Detail`：查看结论、事件与产物
  - `Assets`：管理工作区资料
  - `Methods`：查看沉淀方法
  - `Audit`：查看审计记录
  - `Session Settings`：切换 API 地址与 Bearer Token

### App-facing API

- `GET /api/app/session`
- `GET /api/app/analyses`
- `POST /api/app/analyses`
- `GET /api/app/analyses/{analysis_id}`
- `GET /api/app/analyses/{analysis_id}/events`
- `GET /api/app/analyses/{analysis_id}/outputs/{output_id}`
- `GET /api/app/assets`
- `POST /api/app/assets`
- `GET /api/app/methods`
- `GET /api/app/audit`

### 保留下来的核心协作模块

- `src/blackboard`：任务、执行、知识、记忆状态事实源
- `src/dag_engine`：静态主链与节点编排
- `src/dynamic_engine`：DeerFlow sidecar 适配与动态研究监督
- `src/sandbox`：AST 审计、Docker 执行、执行记录
- `src/kag`：知识构建、检索、上下文压缩
- `src/skillnet`：方法沉淀、历史复用、提升与校验
- `src/api`：app-facing API、认证、运行时与策略接口

## 当前能力边界

### 动态运行时

当前唯一支持的动态运行时是 **DeerFlow sidecar**。

- 支持：动态研究、检索与工具调用、研究轨迹回写、研究后回流静态链
- 不支持：把最终 Python 执行边界交给 DeerFlow
- sidecar 不可用时：明确返回 `unavailable` 语义，不再悄悄回退到 embedded / auto 模式

### 结构化数据输入

当前静态执行链稳定支持：

- `csv`
- `tsv`
- `json`

不应继续对外宣传为稳定静态分析输入：

- `xlsx`
- `xls`
- `parquet`

### 认证与访问控制

- 默认通过 Bearer Token 访问 API
- `/health` 之外的受保护接口按角色校验
- 不再支持 query-string token
- 前端通过 `/api/app/session` 完成会话 bootstrap，并以当前会话可用 workspace 作为产品面真相源
- `viewer / operator / admin` 三层角色仍然保留

### app-facing 合同补充约定

- `/api/app/*` 的列表接口统一支持 `page` / `pageSize`
- 非法分页参数、认证失败、scope 不匹配、上传失败等错误统一返回结构化 error envelope
- `Audit` 页面读取真实分页结果，不再依赖隐式截断后的假总数
- 结果产物下载只允许访问当前任务所属 tenant/workspace 的 upload/output 目录

## 快速开始

### 1. 准备环境

```bash
cd /home/linsir365/projects/lite-interpreter
cp .env.example .env
```

推荐环境：

- conda env：`lite_interpreter`
- Python：`3.12`
- Node.js：18+
- Docker daemon：用于真实 sandbox 执行与部分集成测试

### 2. 启动 API

```bash
cd /home/linsir365/projects/lite-interpreter
conda run -n lite_interpreter python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000
```

### 3. 启动 DeerFlow sidecar（需要动态研究时）

```bash
cd /home/linsir365/projects/lite-interpreter
export DEERFLOW_SIDECAR_URL=http://127.0.0.1:8765
conda run -n lite_interpreter python scripts/run_deerflow_sidecar.py --host 127.0.0.1 --port 8765
```

### 4. 启动 Web 前端

```bash
cd /home/linsir365/projects/lite-interpreter/apps/web
npm install
npm run dev
```

如果你已经构建过前端，也可以直接通过后端挂载的静态站点访问：

```bash
cd /home/linsir365/projects/lite-interpreter/apps/web
npm run build
```

构建产物位于 `apps/web/dist`。当该目录存在时，`src/api/main.py` 会把它挂到 `/`。

### 5. 常用验证命令

```bash
conda run -n lite_interpreter python -m ruff check src tests scripts config
conda run -n lite_interpreter python -m pytest -q
cd apps/web && npm run lint && npm run build
```

## 文档地图

完整文档层次见 `docs/README.md`。如果你只想快速进入正确上下文，按下面顺序读：

### 第一次接手项目

1. `docs/README.md`
2. `docs/reference/project-status.md`
3. `docs/explanation/architecture.md`
4. `directory.txt`
5. `docs/how-to/development.md`

### 想跑起来并验证产品面

1. `docs/tutorials/first-analysis.md`
2. `docs/how-to/deployment.md`
3. `docs/how-to/testing.md`
4. `scripts/create_analysis.py`

### 如果你是业务同学，只想先把一次分析跑通

1. `docs/tutorials/first-analysis.md`
2. 找管理员拿 API 地址和 Bearer Token
3. 用小范围资料先做一次主题明确的分析

### 想理解工程判断与后续方向

1. `项目二.md`
2. `docs/reference/project-status.md`
3. `docs/explanation/architecture.md`

## 仓库导览

- `apps/web`：真实 Web 前端
- `config`：可跟踪配置默认值与策略文件
- `docs`：按 Diataxis 划分的说明文档
- `scripts`：启动、smoke、readiness 与 API 辅助脚本
- `src`：后端源码与核心运行时
- `tests`：自动化测试与契约校验
- `directory.txt`：仓库目录说明与阅读顺序

## 当前工程判断

这个项目已经完成“旧前端 -> 真实 Web 前端”的产品面迁移，也完成了“旧公开接口 -> `/api/app/*` 合同”的 API 收口。

接下来最重要的工作，不是继续加新页面，而是继续做三件事：

1. 保持控制面、动态面、执行面、产品面边界稳定
2. 让文档、测试、配置契约和实际实现保持同步
3. 把已经跑通的分析主链做得更稳，而不是重新引入假支持和隐式行为
