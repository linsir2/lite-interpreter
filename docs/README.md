# 文档地图

这套文档按 **Diataxis** 拆成四类职责，但当前仓库更偏重 `How-to / Reference / Explanation` 三类；面向新同学的“完整 Tutorial”暂时由 `README.md` 的快速开始承担。

如果你感觉以前的文档“都在讲，但都没讲清楚”，从这里开始读，不要再随机翻文件。

## 文档分工

| 文件 | 类型 | 面向谁 | 解决什么问题 |
| --- | --- | --- | --- |
| `README.md` | 入口页 / 轻量 Tutorial | 第一次进入仓库的人 | 这个项目是什么、怎么快速跑起来、先看哪份文档 |
| `docs/user_guide.md` | Tutorial / How-to | 财务、会计、经营分析、业务复核人员 | 如何从连接平台、上传资料走到拿到可复核的分析结果 |
| `docs/project_status.md` | Reference | 所有人 | 当前成熟度、最近验证基线、已知热点、明确非目标 |
| `docs/architecture.md` | Explanation | 开发者、架构维护者 | 各模块为什么这样分层、主链如何协作、边界在哪里 |
| `docs/development_guide.md` | How-to | 日常开发者 | 改动前后该看什么、怎么改、改完至少跑什么 |
| `docs/deployment.md` | How-to | 本地运行/部署维护者 | 如何配置环境、启动 API/sidecar/web、排查常见问题 |
| `docs/testing.md` | Reference + How-to | 开发者、QA | 仓库测试分层、常用命令、不同改动应该验证什么 |
| `directory.txt` | Reference | 新接手开发者 | 仓库目录、关键文件、推荐阅读顺序 |
| `项目二.md` | Explanation | 需要理解项目判断的人 | 这次架构收口做对了什么、还剩什么工程问题 |

## 推荐阅读路径

### 路径 A：第一次接手仓库

1. `README.md`
2. `docs/project_status.md`
3. `docs/architecture.md`
4. `directory.txt`
5. `docs/development_guide.md`

### 路径 B：我要把系统跑起来

1. `README.md`
2. `docs/user_guide.md`
3. `docs/deployment.md`
4. `docs/testing.md`
5. `scripts/create_analysis.py`

### 路径 C：我是业务同学，只想把一次分析跑通

1. `docs/user_guide.md`
2. `README.md`
3. 找管理员要 API 地址和 Bearer Token
4. 先在 Web 前端完成一次小范围分析
### 路径 D：我要改前端或 app-facing API

1. `docs/project_status.md`
2. `docs/architecture.md`
3. `docs/development_guide.md`
4. `apps/web/src/lib/api.ts`
5. `src/api/routers/app_router.py`
6. `src/api/app_schemas.py`

### 路径 E：我要查当前系统还能不能信

1. `docs/project_status.md`
2. `docs/testing.md`
3. `tests/test_api_route_surface.py`
4. `tests/test_api_app.py`
5. `tests/test_docs_consistency.py`

## 文档维护规则

为了避免文档再次漂移，仓库文档按下面的职责维护：

- `docs/project_status.md` 是“状态与基线”的唯一真相源
- `README.md` 只做入口，不记录会快速过期的细节表
- `docs/architecture.md` 只解释结构与边界，不重复部署命令
- `docs/deployment.md` 只讲运行与配置，不重复架构讨论
- `docs/testing.md` 只讲验证方法，不维护项目叙事
- `directory.txt` 只描述目录和入口，不承担实现细节解释

## 当前缺口

当前仓库仍缺一份真正面向“非开发维护者”的产品使用教程。如果后面要补，请新增成独立 `Tutorial`，不要再把使用说明塞回架构文档里。
