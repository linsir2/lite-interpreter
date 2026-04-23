# lite-interpreter 当前状态

## 1. 一句话定位

`lite-interpreter` 当前是一个面向数据分析任务的、受控且可观测的分析运行时原型。它已经完成产品面的真实 Web 前端迁移，但整体仍应被看作“正在工程化收口的系统”，而不是随时可宣称全面产品化的成熟平台。

## 2. 最新验证基线

### 自动化验证

- 最后复验日期：`2026-04-23`
- 验证命令：`conda run -n lite_interpreter python -m pytest -q`
- 最新结果：`244 passed, 4 skipped`
- 说明：4 个 skip 仍来自 Docker / 本地 TCP 绑定等环境能力缺失，而不是已知断言失败

### 前端构建验证

- 最后复验日期：`2026-04-23`
- 验证命令：`cd apps/web && npm run lint && npm run build`
- 最新结果：通过

### 浏览器产品面 smoke

- 最近一次人工浏览器烟测：`2026-04-23`
- 结论：通过
- 备注：当次验证未发现严重 console error、失败请求、坏响应或遗留旧接口调用

### 这轮 app-facing 风险收口

- `/api/app/*` 的列表查询现在会稳定校验 `page` / `pageSize`，非法值不再演变成 500
- app-facing 认证、权限、scope、上传失败等主要错误语义已收口到统一结构化 envelope
- 分析结果下载边界已收紧到“当前 task 的 tenant/workspace upload/output 根目录”
- 审计记录已改为真实分页，前端可访问完整记录而不是截断后的局部结果
- 前端本地缓存的 workspace 会在 session bootstrap 后自动校正到当前会话仍然可用的 workspace

这份文档是仓库内关于“当前成熟度、测试基线、已知热点、非目标”的唯一真相源。其它文档只引用这里，不再各自维护通过数字。

## 3. 当前成熟度分层

### Core

这些部分直接证明主闭环已经成立：

- React/Vite Web 前端主工作台（`apps/web`）
- `/api/app/*` app-facing 合同
- DAG 静态链与 DeerFlow 动态超级节点
- Blackboard / Event Bus / Event Journal 控制面
- Harness 治理与本地 Sandbox 执行边界
- 分析详情、事件轮询、结果产物内容 API

### Support

这些部分明显增强主闭环，但不是判断主闭环是否成立的唯一标准：

- KAG 检索与上下文拼装
- SkillNet 沉淀、授权、历史复用
- workspace 资料库与显式 `assetIds` 挂接
- runtime diagnostics / conformance / capability manifest

### Experimental

这些部分已经可用，但仍不应包装成当前版本的核心承诺：

- `Methods` 与 `Audit` 辅助页面的进一步运营化体验
- 更丰富的产物预览与下载交互
- 更深的前端细粒度状态反馈与长任务交互增强

## 4. 这轮迁移已经明确完成的事

1. 旧 Streamlit 产品前端已退出主产品面，当前只保留真实 Web 前端
2. 旧 `tasks/executions/uploads/...` 风格公开产品接口已从路由表移除
3. 产品前端主合同统一收口到 `/api/app/*`
4. 资料上传、分析创建、事件轮询、结果产物读取已经形成闭环
5. 配置面已收口到 `config/` + `.env(.example)` 的组合，而不是散乱的临时配置文件

## 5. 当前最重要的已知热点

1. `src/sandbox/docker_executor.py` 仍然偏大，后续应继续拆容器生命周期、并发控制和结果映射。
2. `src/dag_engine/nodes/static_codegen.py` 仍然偏模板化，后续应让 `analysis_plan`、skill hints 和知识上下文更深地影响生成策略。
3. Web 前端已经完成形态迁移，但长任务中的更细粒度进度反馈、结果预览和操作回路还可以继续增强。
4. skill usage / outcome 在跨进程并发场景下仍需进一步做原子化持久化。
5. 文档、配置与合同虽然再次完成了一轮同步，但未来每次产品面改动都仍有再次漂移的风险。

## 6. 当前明确非目标

- 不把 DeerFlow 提升为系统 owner
- 不恢复 embedded / auto runtime mode
- 不重新开放旧产品面公开接口
- 不继续宣传未完成闭环的结构化格式支持
- 不把辅助页面包装成比主分析链路更重要的“版本卖点”
