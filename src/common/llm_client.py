"""Unified LiteLLM client for DashScope-backed chat and embeddings."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any, Dict, List

import yaml

from config.settings import LITELLM_CONFIG_PATH
from src.common.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class LiteLLMModelConfig:
    alias: str
    params: Dict[str, Any]


class LiteLLMClient:
    """Resolve model aliases from `litellm_config.yml` and call LiteLLM."""

    _configs: Dict[str, LiteLLMModelConfig] | None = None

    @classmethod
    def _load_configs(cls) -> Dict[str, LiteLLMModelConfig]:
        if cls._configs is not None:
            return cls._configs

        config_path = Path(LITELLM_CONFIG_PATH)
        if not config_path.exists():
            raise FileNotFoundError(f"LiteLLM config not found: {config_path}")

        raw_config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {} # 读取
        model_list = raw_config.get("model_list", []) 
        configs: Dict[str, LiteLLMModelConfig] = {}
        for item in model_list:
            alias = str(item.get("model_name"))
            params = cls._resolve_config_values(dict(item.get("litellm_params", {})))
            configs[alias] = LiteLLMModelConfig(alias=alias, params=params)
        cls._configs = configs
        return configs

    @classmethod
    def _resolve_config_values(cls, payload: Dict[str, Any]) -> Dict[str, Any]:
        resolved: Dict[str, Any] = {}
        for key, value in payload.items():
            if isinstance(value, str) and value.startswith("os.environ/"):
                env_name = value.split("/", 1)[1]
                resolved[key] = os.getenv(env_name, "")
            else:
                resolved[key] = value
        return resolved

    @classmethod
    def get_model_config(cls, alias: str) -> LiteLLMModelConfig:
        configs = cls._load_configs()
        if alias not in configs:
            raise KeyError(f"Unknown LiteLLM model alias: {alias}")
        return configs[alias]

    @classmethod
    def resolve_model_name(cls, alias: str) -> str:
        return str(cls.get_model_config(alias).params.get("model") or alias)

    @classmethod
    def completion(
        cls,
        alias: str,
        messages: List[Dict[str, str]],
        **overrides: Any,
    ) -> Dict[str, Any]:
        from litellm import completion as litellm_completion

        config = cls.get_model_config(alias)
        params = {**config.params, **overrides}
        logger.info(f"[LiteLLM] completion alias={alias} model={params.get('model')}")
        return litellm_completion(messages=messages, **params)

    @classmethod
    async def acompletion(
        cls,
        alias: str,
        messages: List[Dict[str, str]],
        **overrides: Any,
    ) -> Dict[str, Any]:
        config = cls.get_model_config(alias)
        params = {**config.params, **overrides}
        logger.info(f"[LiteLLM] acompletion alias={alias} model={params.get('model')}")
        try:
            from litellm import acompletion as litellm_acompletion

            return await litellm_acompletion(messages=messages, **params)
        except (ImportError, AttributeError):
            return await asyncio.to_thread(cls.completion, alias, messages, **overrides)

    @classmethod
    def chat(
        cls,
        alias: str,
        messages: List[Dict[str, str]],
        **overrides: Any,
    ) -> str:
        response = cls.completion(alias, messages, **overrides)
        return response["choices"][0]["message"]["content"]

    @classmethod
    async def achat(
        cls,
        alias: str,
        messages: List[Dict[str, str]],
        **overrides: Any,
    ) -> str:
        response = await cls.acompletion(alias, messages, **overrides)
        return response["choices"][0]["message"]["content"]

    @classmethod
    def embedding(
        cls,
        alias: str,
        inputs: List[str],
        **overrides: Any,
    ) -> List[List[float]]:
        from litellm import embedding

        config = cls.get_model_config(alias)
        params = {**config.params, **overrides}
        logger.info(f"[LiteLLM] embedding alias={alias} model={params.get('model')} count={len(inputs)}")
        response = embedding(input=inputs, **params)
        return [item["embedding"] for item in response["data"]]

    @classmethod
    async def aembedding(
        cls,
        alias: str,
        inputs: List[str],
        **overrides: Any,
    ) -> List[List[float]]:
        config = cls.get_model_config(alias)
        params = {**config.params, **overrides}
        logger.info(f"[LiteLLM] aembedding alias={alias} model={params.get('model')} count={len(inputs)}")
        try:
            from litellm import aembedding

            response = await aembedding(input=inputs, **params)
            return [item["embedding"] for item in response["data"]]
        except (ImportError, AttributeError):
            return await asyncio.to_thread(cls.embedding, alias, inputs, **overrides)
