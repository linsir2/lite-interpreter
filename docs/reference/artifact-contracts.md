# Artifact Contracts Reference

本文件记录 static generator family 到 artifact contract 的固定映射。

v1 的目标不是生成最花哨的图表，而是保证：

- 有稳定的用户交付物
- 有固定文件名和固定验证规则
- 前端可以在不改公共 API 的前提下预览和下载
- 单次公网查证通过 tool-mediated evidence bundle 进入静态链，而不是让沙箱自己联网

## 1. 排序规则

summarizer / presenter 当前固定排序：

1. 报告类：`.md`, `.pdf`
2. 图表类：`.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`
3. 表格/导出类：`.csv`, `.json`, `.tsv`
4. 诊断类：parser report、audit/debug、内部快照

## 2. Family -> Contract

### `dataset_profile`

必选：

- `analysis_report.md`
- `summary.json`

可选：

- `comparison.csv`

说明：

- v1 暂不强制趋势图
- 如果有分组/趋势，优先先落 `comparison.csv`

### `document_rule_audit`

必选：

- `rule_audit_report.md`
- `rule_checks.json`

说明：

- 文档规则类分析的最小稳定交付面就是“报告 + 检查结果”

### `hybrid_reconciliation`

必选：

- `analysis_report.md`
- `cross_source_findings.json`
- `comparison.csv`

说明：

- v1 用 `comparison.csv` 替代更重的图表引擎

### `input_gap_report`

必选：

- `input_gap_report.md`

可选：

- `requested_inputs.json`

禁止：

- `.png`
- `.jpg`
- `.jpeg`
- `.webp`

（注：`legacy_dataset_aware_generator` 已删除，不再作为有效策略族。）

## 3. 验证规则

executor 后的 artifact verification 当前检查：

- required artifact 是否存在
- artifact path 是否在允许输出根目录下
- artifact 是否属于声明过的文件名集合
- `input_gap_report` 是否产出了被禁止的图表后缀
- 失败时会带 `debug_hints` 返回给 bounded debugger

## 4. Static Evidence Boundary

`research_mode=single_pass` 时，静态链允许一次受控外部取证：

- 工具面：`web_search` / `web_fetch`
- 访问方式：MCP / tool-mediated
- HTTP 约束：只允许 `GET`
- 域名边界：配置白名单
- 结果形态：`StaticEvidenceBundle`
- 沙箱边界：继续离线，只消费已取回的 evidence bundle

## 5. 当前非目标

- 不在 v1 引入重型图表渲染依赖
- 不为前端新增 outputs grouping 公共字段
- 不让“只有内部 JSON、没有交付物”的执行结果冒充成功分析
- 不给沙箱开放原生公网访问
