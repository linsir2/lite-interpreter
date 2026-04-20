"""全局基础配置"""

import json
import os
import socket
from pathlib import Path
from typing import Final

from dotenv import load_dotenv

load_dotenv()


def _env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    raw = raw.strip()
    if not raw:
        return default
    return int(raw)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    raw = raw.strip()
    if not raw:
        return default
    return float(raw)


def _env_csv(name: str, default: str = "") -> list[str]:
    raw = os.getenv(name)
    if raw is None:
        raw = default
    return [item.strip() for item in str(raw).split(",") if item.strip()]


def _env_json_mapping(name: str) -> dict[str, object]:
    raw = os.getenv(name)
    if raw is None:
        return {}
    raw = raw.strip()
    if not raw:
        return {}
    payload = json.loads(raw)
    return payload if isinstance(payload, dict) else {}


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    raw = raw.strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


# 项目基础配置
PROJECT_ROOT = Path(__file__).parent.parent
LITELLM_CONFIG_PATH = PROJECT_ROOT / "litellm_config.yml"
HARNESS_POLICY_PATH = Path(_env_str("HARNESS_POLICY_PATH", str(PROJECT_ROOT / "config" / "harness_policy.yaml")))
ANALYSIS_RUNTIME_POLICY_PATH = Path(
    _env_str("ANALYSIS_RUNTIME_POLICY_PATH", str(PROJECT_ROOT / "config" / "analysis_runtime.yaml"))
)
GRAPH_LEXICON_PATH = Path(_env_str("GRAPH_LEXICON_PATH", str(PROJECT_ROOT / "config" / "graph_lexicon.yaml")))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
PROMETHEUS_PORT = _env_int("PROMETHEUS_PORT", 8000)
DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
LOG_MAX_LENGTH: Final[int] = 10 * 1024 * 1024  # 日志最大长度10MB
TASK_LEASE_TTL_SECONDS: Final[int] = _env_int("TASK_LEASE_TTL_SECONDS", 60)
TASK_LEASE_HEARTBEAT_SECONDS: Final[int] = _env_int("TASK_LEASE_HEARTBEAT_SECONDS", 20)
TASK_SCHEDULER_INSTANCE_ID: Final[str] = _env_str(
    "TASK_SCHEDULER_INSTANCE_ID",
    f"{socket.gethostname()}:{os.getpid()}",
)
# 任务流执行池大小：
# - 用于承载整个同步 DAG 链路（data inspector / kag retriever / sandbox exec 等）
# - 故意与 asyncio 默认线程池隔离，避免重任务把其他轻量 to_thread 回退路径挤满
TASK_FLOW_MAX_WORKERS: Final[int] = _env_int("TASK_FLOW_MAX_WORKERS", 4)
API_ALLOW_ORIGINS: Final[list[str]] = _env_csv(
    "API_ALLOW_ORIGINS",
    "http://127.0.0.1:8501,http://localhost:8501",
)
API_ENABLE_POLICY_API: Final[bool] = _env_bool("API_ENABLE_POLICY_API", False)
API_ENABLE_DEMO_TRACE: Final[bool] = _env_bool("API_ENABLE_DEMO_TRACE", False)
API_ENABLE_DIAGNOSTICS: Final[bool] = _env_bool("API_ENABLE_DIAGNOSTICS", False)
API_AUTH_REQUIRED: Final[bool] = _env_bool("API_AUTH_REQUIRED", True)
API_AUTH_TOKENS: Final[dict[str, object]] = _env_json_mapping("API_AUTH_TOKENS_JSON")
API_AUTH_USERS: Final[dict[str, object]] = _env_json_mapping("API_AUTH_USERS_JSON")
API_SESSION_SECRET: Final[str] = _env_str("API_SESSION_SECRET", "")
API_SESSION_TTL_SECONDS: Final[int] = _env_int("API_SESSION_TTL_SECONDS", 43200)

# 数据与模型缓存目录 (本地沙箱执行时使用)
DATA_DIR = PROJECT_ROOT / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
OUTPUT_DIR = DATA_DIR / "outputs"

# Dynamic engine / DeerFlow integration
# DeerFlow is expected to be installed as a Python package such as
# the `deerflow` package built from DeerFlow's official harness source, not
# vendored into this repository.
DEERFLOW_CLIENT_MODULE = os.getenv("DEERFLOW_CLIENT_MODULE", "deerflow.client").strip()
DEERFLOW_RUNTIME_MODE = _env_str("DEERFLOW_RUNTIME_MODE", "sidecar")
DEERFLOW_SIDECAR_URL = _env_str("DEERFLOW_SIDECAR_URL", "")
DEERFLOW_SIDECAR_TIMEOUT = _env_int("DEERFLOW_SIDECAR_TIMEOUT", 300)
DEERFLOW_CONFIG_PATH = _env_str("DEERFLOW_CONFIG_PATH", "")
DEERFLOW_MODEL_NAME = _env_str("DEERFLOW_MODEL_NAME", "")
DEERFLOW_MAX_EVENTS = _env_int("DEERFLOW_MAX_EVENTS", 64)
DEERFLOW_MAX_STEPS = _env_int("DEERFLOW_MAX_STEPS", 6)
DEERFLOW_RECURSION_LIMIT = _env_int("DEERFLOW_RECURSION_LIMIT", 32)

# 存储层
# Postgres 关系型数据库
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres123")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = _env_str("POSTGRES_PORT", "5432")
POSTGRES_DB = os.getenv("POSTGRES_DB", "kag_db")
POSTGRES_URI = os.getenv(
    "POSTGRES_URI", f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
)

# Neo4j 图数据库
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password123")

# Qdrant 向量数据库
QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = _env_int("QDRANT_PORT", 6333)

# Chunk 切分控制
CHUNK_SIZE: Final[int] = _env_int("CHUNK_SIZE", 800)
CHUNK_OVERLAP: Final[int] = _env_int("CHUNK_OVERLAP", 150)

# 向量维度 (依赖于你使用的 Embedding 模型，如 BGE-m3 设为 1024，OpenAI 设为 1536)
EMBEDDING_DIM: Final[int] = _env_int("EMBEDDING_DIM", 1536)

# Classifier 分流阈值
# 大概是一个chunk分块的大小，检索得来的文段都会进行compress，而small模式下的单chunk也包含在内
CLASSIFIER_SMALL_THRESHOLD = _env_int("CLASSIFIER_SMALL_THRESHOLD", 1500)
CLASSIFIER_MEDIUM_THRESHOLD = _env_int("CLASSIFIER_MEDIUM_THRESHOLD", 50000)

# ==========================================
# DAG 与执行引擎配置
# ==========================================
MAX_RETRIES: Final[int] = _env_int("MAX_RETRIES", 3)  # 节点间允许的最大容错回退次数
CONTEXT_BUDGET_TOKENS: Final[int] = _env_int("CONTEXT_BUDGET_TOKENS", 4000)  # 喂给 Coder 的上下文 Token 预算上限

# ==========================================
# KAG 模块配置
# ==========================================

# 向量化配置
MRL_DIMENSION: Final[int] = _env_int("MRL_DIMENSION", 256)  # MRL降维后的向量维度
EMBEDDING_MODEL_NAME: Final[str] = os.getenv("EMBEDDING_MODEL_NAME", "embedding_model")  # LiteLLM embedding alias
EMBEDDING_BATCH_SIZE: Final[int] = _env_int("EMBEDDING_BATCH_SIZE", 32)  # 批量处理大小

# 图谱抽取配置
EXTRACTION_MODEL_NAME: Final[str] = os.getenv("EXTRACTION_MODEL_NAME", "reasoning_model")  # 实体关系抽取模型别名
GRAPH_TYPES: Final[list[str]] = os.getenv("GRAPH_TYPES", "semantic,temporal,causal,entity").split(",")  # MAGMA图谱类型
GRAPH_EXTRACTOR_VERSION: Final[str] = _env_str("GRAPH_EXTRACTOR_VERSION", "2.0")
GRAPH_STRUCTURED_LLM_ENABLED: Final[bool] = _env_bool("GRAPH_STRUCTURED_LLM_ENABLED", False)

# 分块策略配置
PARENT_CHUNK_SIZE: Final[int] = _env_int("PARENT_CHUNK_SIZE", 2000)  # 父块大小

# Context模块配置
CONTEXT_MAX_TOKENS: Final[int] = _env_int("CONTEXT_MAX_TOKENS", 4000)  # 上下文最大Token数
COMPRESSION_RATIO: Final[float] = _env_float("COMPRESSION_RATIO", 0.3)  # 压缩比例
SELECTION_STRATEGY: Final[str] = os.getenv("SELECTION_STRATEGY", "rrf")  # 选择策略
FORMAT_TEMPLATE: Final[str] = os.getenv("FORMAT_TEMPLATE", "structured")  # 格式化模板
CONTEXT_MODEL_NAME: Final[str] = _env_str("CONTEXT_MODEL_NAME", "reasoning_model")

# 检索配置
BM25_TOP_K: Final[int] = _env_int("BM25_TOP_K", 20)  # BM25召回数量
VECTOR_TOP_K: Final[int] = _env_int("VECTOR_TOP_K", 20)  # 向量召回数量
GRAPH_TOP_K: Final[int] = _env_int("GRAPH_TOP_K", 10)  # 图谱召回数量
HYBRID_RRF_K: Final[int] = _env_int("HYBRID_RRF_K", 60)  # RRF融合数量
RERANK_TOP_K: Final[int] = _env_int("RERANK_TOP_K", 15)  # 重排序后保留数量
MAX_RETRIEVAL_TOP_K: Final[int] = _env_int("MAX_RETRIEVAL_TOP_K", 50)  # 对外暴露的 top_k 上限
RERANK_CANDIDATE_LIMIT: Final[int] = _env_int("RERANK_CANDIDATE_LIMIT", 60)  # 重排前最大候选池
RERANK_CANDIDATE_MULTIPLIER: Final[int] = _env_int("RERANK_CANDIDATE_MULTIPLIER", 4)  # 相对 top_k 的候选扩展倍数

# 监控配置
LANGFUSE_HOST: Final[str] = os.getenv("LANGFUSE_HOST", "http://localhost:3000")  # Langfuse服务地址
LANGFUSE_PUBLIC_KEY: Final[str] = os.getenv("LANGFUSE_PUBLIC_KEY", "")  # Langfuse公钥
LANGFUSE_SECRET_KEY: Final[str] = os.getenv("LANGFUSE_SECRET_KEY", "")  # Langfuse私钥
