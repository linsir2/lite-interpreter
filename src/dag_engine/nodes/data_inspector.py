"""
Data Inspector 数据嗅探节点

核心职责：
1. 增量跳过：只处理 schema 为空的结构化文件，避免重复探查。
2. 三级降级：DuckDB (极速) -> Pandas+Chardet (容错) -> LLM (视觉暴力解析)。
3. 参数透传：必须提取 load_kwargs 供下游 Coder 直接使用。
4. 硬性阻断：若三级防线全线崩溃，立刻阻断 DAG，发布人工介入事件。
"""

import csv
import os
from typing import Any

import chardet
import duckdb
import pandas as pd

from src.blackboard import GlobalStatus, execution_blackboard, global_blackboard
from src.common import get_logger
from src.common.llm_client import LiteLLMClient
from src.dag_engine.graphstate import DagGraphState
from src.prompts.inspector_prompts import DATA_INSPECTOR_SYSTEM_PROMPT, build_llm_fallback_prompt

logger = get_logger(__name__)


def fast_llm_call(prompt: str) -> str:
    """使用 DashScope 上的快速模型完成轻量级结构推断。"""
    try:
        return LiteLLMClient.chat(
            "fast_model",
            [
                {
                    "role": "system",
                    "content": DATA_INSPECTOR_SYSTEM_PROMPT,
                },
                {"role": "user", "content": prompt},
            ],
        )
    except Exception as exc:
        logger.warning(f"[Data Inspector] fast_model 调用失败，降级为规则提示: {exc}")
        return "推测：存在嵌套表头，优先尝试 `skiprows=2, sep='|', encoding='gbk'` 读取。"


def data_inspector_node(state: DagGraphState) -> dict[str, Any]:
    """
    数据探查员：为结构化文件提取 Schema 和读取参数
    """
    tenant_id = state["tenant_id"]
    task_id = state["task_id"]

    logger.info(f"[Data Inspector] 开始为任务 {task_id} 嗅探数据结构...")

    # 1. 广播状态：通知前端正在探查
    global_blackboard.update_global_status(
        task_id=task_id, new_status=GlobalStatus.PREPARING_CONTEXT, sub_status="正在挂载沙箱并极速嗅探数据表结构..."
    )

    exec_data = execution_blackboard.read(tenant_id, task_id)
    if not exec_data or not exec_data.inputs.structured_datasets:
        logger.warning(f"任务 {task_id} 没有需要探查的结构化数据。")
        return {}

    inspection_count = 0
    inspection_failed = False
    failed_file_name = ""
    failed_reason = ""

    for dataset in exec_data.inputs.structured_datasets:
        file_name = dataset.file_name or "unknown.csv"
        file_path = dataset.path

        if not file_path or not os.path.exists(file_path):
            logger.error(f"文件不存在: {file_path}")
            continue

        if dataset.dataset_schema:
            logger.info(f"文件 {file_name} 已探查过，跳过。")
            continue

        logger.info(f"正在探查新文件: {file_name}")
        inspection_result = {"schema": "", "load_kwargs": {}}

        # 第一道防线：duckdb快速探查
        try:
            conn = duckdb.connect(":memory:")
            schema_df = conn.execute(f"DESCRIBE SELECT * FROM read_csv_auto('{file_path}')").df()
            sample_df = conn.execute(f"SELECT * FROM read_csv_auto('{file_path}') LIMIT 5").df()

            inspection_result["schema"] = (
                f"【表结构】\n{schema_df.to_markdown()}\n\n【前5行样例】\n{sample_df.to_markdown()}"
            )
            inspection_result["load_kwargs"] = {}  # 默认参数即可
            logger.info(f"{file_name} -> DuckDB 极速探查成功。")

        except Exception as e_duck:
            logger.warning(f"{file_name} -> DuckDB 探查失败，降级至 Pandas 嗅探模式。报错: {e_duck}")

            # 第二道防线：pandas + chardet 编码分隔符嗅探
            try:
                # 获取文件编码（读取前10kb字节）
                with open(file_path, "rb") as f:
                    raw_data = f.read(10240)
                    encoding = chardet.detect(raw_data)["encoding"] or "utf-8"

                # 获取分隔符
                with open(file_path, encoding=encoding, errors="ignore") as f:
                    sample_text = f.read(4096)
                    try:
                        dialect = csv.Sniffer().sniff(sample_text)
                        sep = dialect.delimiter
                    except csv.Error:
                        sep = ","

                df = pd.read_csv(file_path, nrows=5, encoding=encoding, sep=sep, engine="python")

                inspection_result["schema"] = (
                    f"【表结构】\n{df.dtypes.to_markdown()}\n\n【样本数据】\n{df.head(5).to_markdown()}"
                )
                inspection_result["load_kwargs"] = {"encoding": encoding, "sep": sep}
                logger.info(f"{file_name} -> Pandas 嗅探成功 (编码: {encoding}, 分隔符: '{sep}')")

            except Exception as e_pandas:
                logger.warning(f"{file_name} -> Pandas 嗅探失败，降级至 LLM 暴力视觉解析。报错: {e_pandas}")

                # LLM解析表结构
                try:
                    with open(file_path, errors="ignore") as f:
                        head_text = "".join([f.readline() for _ in range(50)])

                    prompt = build_llm_fallback_prompt(head_text)
                    llm_response = fast_llm_call(prompt)
                    inspection_result["schema"] = f"【LLM视觉推断表头】\n{llm_response}"
                    inspection_result["load_kwargs"] = {
                        "note": "非常规格式，请参考 Schema 中的 LLM 建议编写 Pandas 读取参数"
                    }
                    logger.info(f"{file_name} -> LLM 解析完成。")

                except Exception as e_llm:
                    error_msg = f"文件格式严重损坏或完全无法识别。DuckDB/Pandas/LLM 全崩溃: {str(e_llm)}"
                    logger.error(f"{file_name} -> {error_msg}")
                    inspection_failed = True
                    failed_file_name = file_name
                    failed_reason = error_msg
                    break  # 跳出循环，不需要继续探查了，直接终止任务

        if not inspection_failed:
            dataset.dataset_schema = inspection_result["schema"]
            dataset.load_kwargs = inspection_result["load_kwargs"]
            # 逐个文件增量落盘：
            # 这样如果节点在后续文件上中途崩溃，前面已经探查完成的数据集
            # 不会因为整个节点尚未结束而全部丢失。
            execution_blackboard.write(tenant_id, task_id, exec_data)
            execution_blackboard.persist(tenant_id, task_id)
            inspection_count += 1

    if inspection_failed:
        global_blackboard.update_global_status(
            task_id=task_id,
            new_status=GlobalStatus.WAITING_FOR_HUMAN,
            sub_status=f"数据文件 [{failed_file_name}] 解析彻底失败，需人工介入清洗。",
        )

        exec_data.static.latest_error_traceback = failed_reason
        execution_blackboard.write(tenant_id, task_id, exec_data)
        execution_blackboard.persist(tenant_id, task_id)
        logger.info(f"[Data Inspector] 嗅探失败，已阻断后续静态链。共处理 {inspection_count} 个新文件。")
        return {
            "blocked": True,
            "block_reason": failed_reason,
            "next_actions": ["wait_for_human"],
        }

    execution_blackboard.write(tenant_id, task_id, exec_data)
    execution_blackboard.persist(tenant_id, task_id)
    logger.info(f"[Data Inspector] 嗅探完毕，共处理 {inspection_count} 个新文件，结果已落盘。")
    return {"blocked": False}
