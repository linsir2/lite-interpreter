# AGENTS.md - lite-interpreter 项目知识库

## 项目概述

**项目名称**: lite-interpreter（知识增强的代码解释器系统）
**核心功能**: 结合知识图谱增强的代码解释和分析系统
**开发阶段**: 按照 directory.txt 中的六个阶段进行开发

## 项目结构

### 目录结构
```
lite-interpreter/
├── config/              # 配置层：全局配置管理
├── src/                 # 核心源码层：所有业务代码
│   ├── storage/         # 统一数据访问层（DAL）
│   ├── sandbox/         # 安全沙箱引擎（第一阶段）
│   ├── blackboard/      # 全局黑板状态中枢（第二阶段）
│   ├── privacy/         # PII数据脱敏与隐私保护（第二阶段）
│   ├── dag_engine/      # DAG确定性执行引擎（第三阶段）
│   ├── kag/             # KAG静态知识流（第四阶段）
│   ├── mcp_gateway/     # MCP标准化协议网关（第四阶段）
│   ├── skillnet/        # Skillnet自进化技能网络（第五阶段）
│   ├── api/             # FastAPI接口层（第六阶段）
│   ├── frontend/        # Streamlit前端界面（第六阶段）
│   └── common/          # 公共工具层
├── tests/               # 自动化测试用例
├── docs/                # 项目文档
└── data/                # 本地数据目录（git忽略）
```

### 关键文件
- `directory.txt`: 项目完整结构和文件协作关系
- `src/storage/schema.py`: 统一数据架构定义
- `src/kag/builder/classifier.py`: 文档复杂度分类器
- `src/dag_engine/nodes/kag_retriever.py`: 调用KAG进行检索，kag模块的代码必须符合该文件中的引用与设计
- `src/kag/retriever/recall/hybrid_search.py`: 混合检索实现  

## kag（知识图谱增强）模块规范

### 技术栈
- **文档解析**: Docling
- **检索框架**: llama-index
- **模型调用**: litellm
- **图谱存储**: neo4j
- **监控追踪**: langfuse

### 数据架构
- 预定义 `schema.py` 存储定义的数据架构
- 参考 `src/storage/schema.py` 中的模型定义：
  - `DocChunk`: 文本块存储模型
  - `EntityNode`: 图谱实体节点模型
  - `KnowledgeTriple`: 知识三元组模型
  - `StructuredDatasetMeta`: 结构化数据表元数据

### 图谱设计 - MAGMA（多维正交图谱）
**核心原则**: 使用强约束，不使用 openie，拆分为四张正交图：

1. **语义图 (Semantic Graph)**
   - 基于文本内容的语义关系
   - 实体间的概念关联

2. **时序图 (Temporal Graph)**
   - 时间序列关系
   - 事件的时间先后顺序

3. **因果图 (Causal Graph)**
   - 因果关系推理
   - 条件依赖关系

4. **实体图 (Entity Graph)**
   - 实体识别与链接
   - 实体属性关系

**优势**: 检索时先通过元数据过滤，提高检索效率

### 分块策略
三层分块策略，防止巨型章节：

1. **结构化感知 (Layout-aware)**
   - 基于文档结构（标题、段落、列表等）进行分块

2. **按节定父块 (Parent-child Chunking)**
   - 父子分块关系，保持上下文连贯性

3. **长度兜底防御 (SentenceSplitter 兜底)**
   - 当上述策略失效时，使用 SentenceSplitter 进行安全分块

### 向量化策略
1. **叶子节点计算**: 只挑出 Leaf（叶子节点）计算向量
2. **MRL 降维**: 把叶子节点的向量截断到 256 维
3. **存储**: 降维后的向量存入 Qdrant

### 模型选择
- 使用 qwen/deepseek 相关模型
- 多个模型分工，各自负责擅长的任务
- **轻量与复杂的取舍**: 简单任务使用轻量模型，复杂任务使用强大模型

### 检索策略
1. **文档分类**: 参照 classifier 中的 small/medium/large 分类
2. **混合检索**: 使用 rrf（Reciprocal Rank Fusion）算法
3. **多路召回**: BM25、SPLADE、图谱搜索等
4. **元数据过滤**: 检索时先通过元数据过滤

### 监控与追踪
- 使用 **langfuse** 监测整个 kag 模块的 pipeline
- 追踪文档解析、分块、向量化、检索等各个环节

### 文档分类标准
参照 `src/kag/builder/classifier.py`:
- **SMALL**: 单 chunk，直接向量化（≤ CLASSIFIER_SMALL_THRESHOLD）
- **MEDIUM**: 分块 + 向量化（≤ CLASSIFIER_MEDIUM_THRESHOLD）
- **LARGE**: 分块 + 向量化 + 图谱抽取（> CLASSIFIER_MEDIUM_THRESHOLD）

## 开发工作流

### 常用命令
```bash
# 安装依赖
pip install -r requirements.txt

# 运行测试
pytest tests/

# 查看项目结构
cat directory.txt
```

### 代码规范
- 遵循 Python PEP 8 规范
- 使用类型注解
- 模块化设计，高内聚低耦合

## 需要改进的方面

### 短期改进
1. 实现 MAGMA 多维正交图谱（语义、时序、因果、实体）
2. 集成 Docling 进行文档解析
3. 实现 langfuse 监控集成
4. 实现分块策略（结构化感知 + 父子分块）
5. 优化向量化策略（叶子节点 + MRL 降维）
6. 实现多模型分工调用

### 长期改进
1. 性能优化和缓存策略
  - 针对于检索缓存：为了在保证响应质量的同时显著降低延迟与成本，系统通常会设计一套分层、互补的缓存策略。最基础的一层是精确匹配缓存：将完整的输入 Prompt（或其哈希）作为 Key，直接映射到历史生成的回复，用于拦截大量完全相同的高频请求。更进一步是语义缓存：当新请求到达时，先用轻量级 Embedding 模型将其向量化，并在向量数据库中与历史请求计算余弦相似度；若相似度超过很高阈值（例如 0.95），即可直接返回命中的历史结果，从而跳过大模型推理。对于长文档或固定上下文的场景，还可以采用上下文预缓存（也称 prompt caching）：利用模型的显式缓存能力预先“存入”文档内容或系统提示词，使后续请求只需付出少量 token 成本即可复用这些上下文。最后，为了应对突发热点带来的并发洪峰，需要引入请求合并机制：当大量用户在极短时间内询问同一问题时，通过分布式锁将并发的相同请求挂起，只向下游模型发起一次调用，待结果返回后再统一分发给所有等待的请求，以避免缓存击穿并保护后端基础设施。
  
2. 分布式处理支持
3. 更智能的检索优化

## 注意事项

1. **文件协作**: 重点阅读 `directory.txt`，注意文档各自的内容以及之间的协作关系
2. **模块边界**: kag 模块专注于非结构化文档处理，结构化数据由 DAG Router 引流至 Inspector
3. **错误处理**: 完善的异常处理和日志记录
4. **性能考虑**: 考虑大规模文档处理时的性能和资源消耗

---

*最后更新: 2026-03-30*
*维护者: OpenHands Agent*