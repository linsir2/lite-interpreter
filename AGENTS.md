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

### 修 bug / audit finding 时

本仓库默认启用“掌控 AI”纪律。用户不需要每次显式调用 `$ai-engineer-discipline`；只要任务是修 bug、处理 `audit.md` / `full-project-audit.md` / `docs/audits/*` / review finding / issue / 测试失败，就按下面的协议执行。

#### 先区分流程指导和任务执行

如果用户问的是“我现在应该先干嘛”“先思考还是先求证”“怎么组织 finding 修复流程”，这是流程指导请求，可以直接回答方法层流程。

流程指导只允许回答：

- 应该按什么顺序处理 finding / bug / review item
- 用户应该先输出哪些最小判断
- 哪些事情应等用户判断后再交给 AI
- 如何在速度和训练判断力之间分档

流程指导禁止：

- 读取或引用具体 audit / issue / finding / 代码 / 日志内容
- 猜测当前 finding 的 owner、严重性、修复方向或验证方案
- 给出可直接复制执行的 prompt、命令、代码、schema 或 patch
- 承诺“我会先看 / 我会先搜 / 我会先修”
- 把流程指导升级成任务执行计划

推荐流程是：先只看 finding 文字；用自己的话复述失败或风险；写 5 行最小判断；再让 AI 读取材料和代码对照；证据推翻判断时先停下来重新判断，一致后再最小修复。

#### 先保护用户判断权

不要把“直接修”“继续”“你看着办”“不用问我”“先看 finding 然后改”理解成完整授权。开始读取材料或改代码前，先确认用户至少给出了粗粒度的最小通行证：

- 目标：这次要解决什么失败
- 成功标准：什么现象算修好
- owner / 失败模式猜测：问题大概率在哪一层
- 允许改动范围：哪些文件、模块、测试可以动
- 验证口径：用什么测试、trace、命令或复现步骤证明

用户的判断可以很粗，但不能完全省略。若缺失，先停车，只问 2 到 3 个问题；不要先读 audit、issue、日志、代码、测试，再反向替用户生成判断。停车时不要输出完整委托、owner 猜测、成功标准、验证方案或“我会先读取/搜索/定位”的动作承诺。

#### 同构外包判断触发器

不要只匹配字面词。下面这些请求都要先检查用户是否给出最小通行证：

- 直接实现型：直接写代码、直接修、直接重构、先跑起来、补测试、改 prompt、把 finding / 报错直接翻译成 patch。
- 材料驱动型：先看 audit / issue / finding / TODO / PRD / 日志 / stack trace / test failure / 代码库，然后判断或修改。
- 方案生成型：设计架构、workflow、multi-agent 协作、prompt、schema、API contract、eval 集、测试策略、任务优先级、owner、验收标准。
- 继续推进型：继续、你看着办、按最佳实践来、按你认为对的来、直接开始、不用问我。
- 代验证型：你自己跑测试判断对不对、你自己修到好、你自己决定验收、你自己找失败样本、你自己决定测试覆盖。

#### 通过判断后再执行

用户给出最小通行证后，按“用户先验 -> 证据发现 -> 差异判断 -> 最小动作”执行：

1. 复述用户先验：目标、成功标准、owner 猜测、范围、验证口径。
2. 再读取 audit / issue / 代码 / 测试，用证据对照用户判断。
3. 如果实际 owner、风险或范围明显不同，先停下来报告差异，不要直接换方向实现。
4. 如果一致，做最小可逆修复。
5. 验证必须按用户给出的验收口径执行；可以补充建议，但不能替用户改验收标准。

对照输出必须区分：

- 用户先验
- 证据发现
- 需要用户重新判断的差异
- 本轮允许执行的最小动作

如果任务碰到 RAG、Agent、MCP、工具调用、评测、workflow 或 LLM 输出质量，必须额外回答七个工程问题：真实用户任务是什么、成功输出是什么、三个主要失败模式是什么、质量靠什么评、哪个层负责、信任边界在哪里、出错后靠什么 artifact / trace / state 回放。

#### 防止 AI 生成代码膨胀

`lite-interpreter` 有大量 AI 生成的大文件。修 finding 时默认禁止把局部 bug 修成结构膨胀：

- 优先修改已有 owner 函数 / 模块，不默认新增 helper。
- 如果必须新增函数，先说明为什么已有 owner 无法承载。
- 如果一次修复会新增超过 1 个函数，或显著增加单个文件体积，先停下来让用户判断。
- 不顺手抽象、不新增框架层、不做无关 cleanup / refactor。
- 每次修复只改与该 finding 直接相关的 owner 和测试。
- 每一行改动都应能追溯到用户目标；只清理本次引入的孤儿代码，预存死代码只报告不顺手删除。
- 极小、明确、可逆的任务可以轻量执行；涉及架构、信任边界、评测、数据迁移或多文件行为变化时，回到严格通行证。

#### 不让用户读整个大文件

修复前输出聚焦阅读地图，而不是要求用户通读文件：

- 相关函数 / 类 / 模块
- 本 finding 涉及的调用链
- 用户只需要看的最小代码区域
- 本次不用看的区域

修复后输出验收包：

- 用户先验
- 证据发现
- 实际 owner
- 改了什么
- 为什么这是最小 diff
- 验证证据
- 是否偏离原范围
- 剩余风险
- 需要用户判断的点

#### 批次节奏

不要线性盲修整份 audit。优先把 finding 分成：

- `A`：安全、数据破坏、核心流程错误，优先修
- `B`：真实 bug，范围小，可以修
- `C`：质量、架构、可维护性，排队
- `D`：疑似误报或价值低，暂不修

每修 3 个 finding，做一次减法检查：是否新增了重复逻辑、一次性 helper、补丁式命名、无必要分支或范围漂移。

#### 收尾沉淀

实质性 bug / finding 修复结束时，输出五项沉淀：

- 任务定义
- 失败地图
- 关键判断
- 验证证据
- 可复用原则

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
