# lite-interpreter 部署与运行说明

本文件是 **How-to Guide**：只讲如何配置、启动、构建和排查，不重复架构讨论。

当前成熟度、测试基线与已知热点统一以 `docs/reference/project-status.md` 为准。

## 1. 使用前先确定场景

### 本地开发场景

适合你要做前端、API、交互或联调：

- 启动 API
- 按需启动 DeerFlow sidecar
- 启动 `apps/web` 的 Vite 开发服务器

### 本地验收 / 近生产场景

适合你要验证后端直接挂载前端产物：

- 先构建 `apps/web/dist`
- 再启动 API
- 由 Starlette 挂载静态站点到 `/`

## 2. 依赖前提

至少准备：

- conda env：`lite_interpreter`
- Python：`3.12`
- Node.js：18+
- Docker daemon
- Postgres
- Qdrant
- Neo4j
- 可选：DeerFlow sidecar

## 3. 配置分层

当前配置面已经收口成三层：

### 3.1 跟踪在仓库里的默认配置

- `config/settings.py`：环境变量读取与默认值
- `config/deerflow_sidecar.yaml`：DeerFlow sidecar 默认配置
- `config/harness_policy.yaml`：治理策略
- `config/analysis_runtime.yaml`：运行时策略
- `config/graph_lexicon.yaml`：图谱/语义词汇配置

### 3.2 本地环境与密钥

- `.env`：本地运行时环境变量
- `.env.example`：环境变量契约模板

### 3.3 不应混进仓库的内容

- 真实生产密钥
- 本机临时联调地址
- 临时调试 token

## 4. 最小可运行配置

最小建议做法：

```bash
cd /home/linsir365/projects/lite-interpreter
cp .env.example .env
```

至少检查这些值：

### API 与前端联调

- `API_ALLOW_ORIGINS=http://127.0.0.1:5173,http://localhost:5173`
- `API_AUTH_REQUIRED=true`
- `API_AUTH_TOKENS_JSON=...`
- 如果你临时设成 `API_AUTH_REQUIRED=false` 做本地联调，也要确认默认 scope：
  - `API_LOCAL_TENANT_ID=local-tenant`
  - `API_LOCAL_WORKSPACE_ID=local-workspace`

### 动态运行时

- `DEERFLOW_RUNTIME_MODE=sidecar`
- `DEERFLOW_SIDECAR_URL=http://127.0.0.1:8765`
- `DEERFLOW_CONFIG_PATH=config/deerflow_sidecar.yaml`

### 外部依赖

- `POSTGRES_URI=...`
- `NEO4J_URI=...`
- `NEO4J_USER=...`
- `NEO4J_PASSWORD=...`
- `QDRANT_HOST=...`
- `QDRANT_PORT=...`

## 5. 启动顺序

### 5.1 安装前端依赖

```bash
cd /home/linsir365/projects/lite-interpreter/apps/web
npm install
```

### 5.2 启动 API

```bash
cd /home/linsir365/projects/lite-interpreter
conda run -n lite_interpreter python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000
```

### 5.3 启动 DeerFlow sidecar（按需）

```bash
cd /home/linsir365/projects/lite-interpreter
export DEERFLOW_SIDECAR_URL=http://127.0.0.1:8765
conda run -n lite_interpreter python scripts/run_deerflow_sidecar.py --host 127.0.0.1 --port 8765
```

### 5.4 启动 Web 前端（开发模式）

```bash
cd /home/linsir365/projects/lite-interpreter/apps/web
npm run dev
```

Vite 默认端口：`5173`

如果需要改开发代理目标，可设置：

```bash
export VITE_DEV_API_PROXY=http://127.0.0.1:8000
```

### 5.5 构建前端（近生产验收）

```bash
cd /home/linsir365/projects/lite-interpreter/apps/web
npm run build
```

当 `apps/web/dist` 存在时，`src/api/main.py` 会把它挂载到 `/`，你可以直接打开后端地址查看页面。

## 6. 常用 Make 入口

```bash
make run-api
make run-sidecar
make run-web
make build-web
make create-analysis
make test
make lint-all
```

## 7. 产品面合同边界

### 7.1 当前主产品接口

前端主工作台只应该依赖：

- `/api/app/session`
- `/api/app/analyses`
- `/api/app/analyses/{analysis_id}`
- `/api/app/analyses/{analysis_id}/events`
- `/api/app/analyses/{analysis_id}/outputs/{output_id}`
- `/api/app/assets`
- `/api/app/methods`
- `/api/app/audit`

### 7.2 已经不该继续使用的旧接口

不要再把 legacy task / execution / upload / session 风格的公开接口当产品前端依赖。

当前产品前端的正式合同只有 `/api/app/*`；旧公开接口的精确移除集合由 `tests/test_api_route_surface.py` 持续守卫。

## 8. 结构化输入边界

当前静态链可靠支持：

- `csv`
- `tsv`
- `json`

当前不应再宣传为稳定静态链输入：

- `xlsx`
- `xls`
- `parquet`

建议先预转换，再上传到工作区。

## 9. 验收命令

### 后端

```bash
cd /home/linsir365/projects/lite-interpreter
conda run -n lite_interpreter python -m pytest -q
conda run -n lite_interpreter python -m ruff check src tests scripts config
```

### 前端

```bash
cd /home/linsir365/projects/lite-interpreter/apps/web
npm run lint
npm run build
```

### app-facing API 快速验收

```bash
cd /home/linsir365/projects/lite-interpreter
conda run -n lite_interpreter python scripts/create_analysis.py --api-base-url http://127.0.0.1:8000 --access-token operator-token
```

## 10. 故障排查

### API 能启动，但前端调不通

优先检查：

- `API_ALLOW_ORIGINS` 是否包含 `http://127.0.0.1:5173`
- Bearer Token 是否有效
- 当前 token 是否对目标 workspace 有 grant

### 动态链一直 `unavailable`

优先检查：

- `DEERFLOW_SIDECAR_URL` 是否正确
- sidecar 是否真的在监听
- `DEERFLOW_RUNTIME_MODE` 是否仍然是 `sidecar`

### 前端能打开，但看不到数据

优先检查：

- `GET /api/app/session` 是否返回当前会话
- `workspaceId` 是否落在当前 token 的 grants 内
- `/api/app/analyses` 是否带上了 Bearer Token

### 产物不能下载或预览

优先检查：

- 前端是否走 `outputs/{output_id}` 内容 API
- 产物路径是否位于受控上传目录或输出目录下
- 是否误把任意绝对路径当作前端直连文件

## 11. 本地历史残留清理

迁移到真实 Web 前端后，开发机上可能仍残留一些旧时代目录或本地状态。

先做 dry-run 审计：

```bash
cd /home/linsir365/projects/lite-interpreter
python scripts/audit_local_residue.py
```

脚本会把结果分成两类：

- `safe historical residue`
  - 明确属于旧产品面残留，可在你确认后显式删除
- `review-first local state`
  - 可能仍是当前运行态、日志或本地工具状态，只建议人工检查，不默认删除

如果你确认要删除安全残留，再显式执行：

```bash
cd /home/linsir365/projects/lite-interpreter
python scripts/audit_local_residue.py --delete
```

当前默认的安全残留清单主要覆盖：

- 旧前端留下的本地偏好目录（由脚本负责精确识别）

而下面这些目录或文件只会被报告，不会被脚本自动删除：

- `.deer-flow/`
- `.omx/`
- `data/`
- `logs/`
- `config.yaml`
