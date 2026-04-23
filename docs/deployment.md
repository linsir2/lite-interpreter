# lite-interpreter 部署与运行说明

## 1. 运行前提

当前成熟度、测试基线与已知热点以 `docs/project_status.md` 为准；本文件只讲部署与运行。

部署这个项目，至少要准备：

- conda env：`lite_interpreter`
- Python：`3.12`
- DashScope API Key
- Postgres
- Qdrant
- Neo4j
- Docker daemon
- 可选：DeerFlow sidecar

## 2. 关键环境变量

### 2.1 模型与运行时

- `DASHSCOPE_API_KEY`
- `DEERFLOW_SIDECAR_URL`
- `DEERFLOW_CONFIG_PATH`
- `DEERFLOW_MODEL_NAME`
- `DEERFLOW_RUNTIME_MODE`（当前推荐固定为 `sidecar`）

### 2.2 持久化与外部依赖

- `POSTGRES_URI`
- `QDRANT_HOST`
- `QDRANT_PORT`
- `NEO4J_URI`
- `NEO4J_USER`
- `NEO4J_PASSWORD`

### 2.3 API 与前端

- `API_ALLOW_ORIGINS`
- `API_ENABLE_DIAGNOSTICS`
- `API_ENABLE_POLICY_API`
- `UPLOAD_MAX_FILE_BYTES`
- `UPLOAD_MAX_REQUEST_BYTES`

### 2.4 认证

- `API_AUTH_REQUIRED`
- `API_AUTH_TOKENS_JSON`

说明：

- 当前版本默认走更保守的安全姿态，建议明确设置认证配置。

配置分层建议：
- `config/*.yaml`：项目内可跟踪的默认配置
- `.env`：本地环境与密钥
- `.env.example`：环境变量契约模板

## 3. 启动顺序

### 3.1 启动 API

```bash
cd /home/linsir365/projects/lite-interpreter
conda run -n lite_interpreter python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000
```

### 3.2 启动 DeerFlow sidecar

```bash
cd /home/linsir365/projects/lite-interpreter
export DEERFLOW_SIDECAR_URL=http://127.0.0.1:8765
conda run -n lite_interpreter python scripts/run_deerflow_sidecar.py --host 127.0.0.1 --port 8765
```

### 3.3 启动 Web 前端

```bash
cd /home/linsir365/projects/lite-interpreter
cd /home/linsir365/projects/lite-interpreter/apps/web
npm install
npm run dev
```

说明：

- 当前 Web 前端通过 `/api/app/*` 读取稳定的 app-facing 合同，并通过 polling 拉取分析事件。
- 前端开发服务器默认代理 `/api` 到后端，生产构建产物位于 `apps/web/dist`。

## 4. 推荐配置

### 4.1 动态运行时

推荐固定：

```bash
export DEERFLOW_RUNTIME_MODE=sidecar
export DEERFLOW_SIDECAR_URL=http://127.0.0.1:8765
```

当前不建议再尝试 embedded / auto 模式，因为仓库内已经明确收口到 sidecar-only 语义。

### 4.2 API 认证示例

```bash
export API_AUTH_REQUIRED=true
export API_AUTH_TOKENS_JSON='{
  "viewer-token":{"tenant_id":"demo-tenant","workspace_id":"demo-workspace","role":"viewer","subject":"viewer-user"},
  "operator-token":{"tenant_id":"demo-tenant","workspace_id":"demo-workspace","role":"operator","subject":"operator-user"},
  "admin-token":{"tenant_id":"demo-tenant","workspace_id":"demo-workspace","role":"admin","subject":"admin-user"}
}'
```

## 5. 当前格式支持边界

### 结构化数据

当前静态链稳定支持：

- `csv`
- `tsv`
- `json`

不建议直接上传到静态执行链：

- `xlsx`
- `xls`
- `parquet`

建议先预转换，再上传。

### 5.1 上传接口行为

当前 `/api/app/assets` 行为：

- 支持单文件上传
- 支持多文件上传
- 单文件上传返回兼容结构
- 多文件上传返回 `uploaded_files` + `file_count`
- 超过上传限制时返回 `413`

如果你要让 workspace 资产进入新任务，不是自动发生的，需要在创建任务时传：

- `assetIds`

其值是 `/api/app/assets` 返回的 `assetId` 列表。

### 业务文档

当前业务文档主格式：

- `pdf`
- `md`
- `txt`
- `docx`
- `doc`

## 6. 常用验收命令

### 全量测试

```bash
conda run -n lite_interpreter python -m pytest -q
```

### 快速检查

```bash
conda run -n lite_interpreter python -m ruff check src tests scripts config
python3 scripts/check_hybrid_readiness.py
```

### 关键运行命令

```bash
make run-api
make run-sidecar
make run-web
make test-stream
make smoke-models
```

## 7. 故障排查

### API 起不来

先看：

- `API_AUTH_REQUIRED` 是否和当前 token/session 配置匹配
- `POSTGRES_URI` 是否可连接

### 动态链一直 unavailable

先看：

- `DEERFLOW_SIDECAR_URL` 是否正确
- sidecar 是否真的在监听
- `scripts/run_deerflow_sidecar.py` 是否正常启动

### KAG 只走稀疏召回

先看：

- Qdrant / Neo4j 是否可达
- 这是当前版本的预期降级行为，不应把节点打崩

### 前端看不到实时状态

先看：

- 前端现在走 polling，不再是浏览器 `EventSource + query token`
- 检查 `Authorization` header 对应 token 是否有权限
- 检查 task/execution poll 接口是否返回事件
