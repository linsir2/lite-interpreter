"""Unified LiteLLM client for DashScope-backed chat and embeddings."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from config.settings import LITELLM_CONFIG_PATH

from src.common.logger import get_logger
from src.kag.compiler.types import LLMHealthStatus

logger = get_logger(__name__)


@dataclass(frozen=True)
class LiteLLMModelConfig:
    alias: str
    params: dict[str, Any]


class LiteLLMClient:
    """Resolve model aliases from `litellm_config.yml` and call LiteLLM."""

    _configs: dict[str, LiteLLMModelConfig] | None = None

    @classmethod
    def _load_configs(cls) -> dict[str, LiteLLMModelConfig]:
        if cls._configs is not None:
            return cls._configs

        config_path = Path(LITELLM_CONFIG_PATH)
        if not config_path.exists():
            raise FileNotFoundError(f"LiteLLM config not found: {config_path}")

        raw_config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}  # 读取
        model_list = raw_config.get("model_list", [])
        configs: dict[str, LiteLLMModelConfig] = {}
        for item in model_list:
            alias = str(item.get("model_name"))
            params = cls._resolve_config_values(dict(item.get("litellm_params", {})))
            configs[alias] = LiteLLMModelConfig(alias=alias, params=params)
        cls._configs = configs
        return configs

    @classmethod
    def _resolve_config_values(cls, payload: dict[str, Any]) -> dict[str, Any]:
        resolved: dict[str, Any] = {}
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
    def _provider_for_alias(cls, alias: str) -> str:
        model_name = cls.resolve_model_name(alias)
        if "/" in model_name:
            return model_name.split("/", 1)[0]
        return "unknown"

    @classmethod
    def completion(
        cls,
        alias: str,
        messages: list[dict[str, str]],
        **overrides: Any,
    ) -> dict[str, Any]:
        from litellm import completion as litellm_completion

        config = cls.get_model_config(alias)
        params = {**config.params, **overrides}
        logger.info(f"[LiteLLM] completion alias={alias} model={params.get('model')}")
        return litellm_completion(messages=messages, **params)

    @classmethod
    async def acompletion(
        cls,
        alias: str,
        messages: list[dict[str, str]],
        **overrides: Any,
    ) -> dict[str, Any]:
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
        messages: list[dict[str, str]],
        **overrides: Any,
    ) -> str:
        response = cls.completion(alias, messages, **overrides)
        return response["choices"][0]["message"]["content"]

    @classmethod
    async def achat(
        cls,
        alias: str,
        messages: list[dict[str, str]],
        **overrides: Any,
    ) -> str:
        response = await cls.acompletion(alias, messages, **overrides)
        return response["choices"][0]["message"]["content"]

    @classmethod
    def embedding(
        cls,
        alias: str,
        inputs: list[str],
        **overrides: Any,
    ) -> list[list[float]]:
        from litellm import embedding

        config = cls.get_model_config(alias)
        params = {**config.params, **overrides}
        logger.info(f"[LiteLLM] embedding alias={alias} model={params.get('model')} count={len(inputs)}")
        response = embedding(input=inputs, **params)
        return [item["embedding"] for item in response["data"]]

    @classmethod
    def probe_alias(cls, alias: str, *, live: bool = False) -> LLMHealthStatus:
        try:
            config = cls.get_model_config(alias)
        except Exception as exc:
            return LLMHealthStatus(
                alias=alias,
                model=alias,
                provider="unknown",
                api_key_present=False,
                configured=False,
                reachable=False,
                smoke_ok=False,
                error=str(exc),
            )
        model_name = str(config.params.get("model") or alias)
        provider = cls._provider_for_alias(alias)
        api_key_present = bool(str(config.params.get("api_key") or "").strip())
        is_embedding = "embedding" in alias or "embedding" in model_name
        status = LLMHealthStatus(
            alias=alias,
            model=model_name,
            provider=provider,
            api_key_present=api_key_present,
            configured=bool(model_name) and api_key_present,
            reachable=False,
            smoke_ok=False,
            is_embedding=is_embedding,
        )
        if not live:
            return status.model_copy(update={"reachable": api_key_present, "smoke_ok": api_key_present})
        if not api_key_present:
            return status.model_copy(update={"error": "missing_api_key"})
        try:
            if is_embedding:
                vectors = cls.embedding(alias, ["lite-interpreter health probe"])
                ok = bool(vectors and isinstance(vectors[0], list))
            else:
                content = cls.chat(alias, [{"role": "user", "content": "reply with ok"}], max_tokens=8)
                ok = bool(str(content).strip())
            return status.model_copy(update={"reachable": ok, "smoke_ok": ok})
        except Exception as exc:
            return status.model_copy(update={"reachable": False, "smoke_ok": False, "error": str(exc)})

    @classmethod
    def probe_required_aliases(cls, *, live: bool = False) -> dict[str, LLMHealthStatus]:
        aliases = ("fast_model", "reasoning_model", "embedding_model")
        return {alias: cls.probe_alias(alias, live=live) for alias in aliases}

    @classmethod
    async def aembedding(
        cls,
        alias: str,
        inputs: list[str],
        **overrides: Any,
    ) -> list[list[float]]:
        config = cls.get_model_config(alias)
        params = {**config.params, **overrides}
        logger.info(f"[LiteLLM] aembedding alias={alias} model={params.get('model')} count={len(inputs)}")
        try:
            from litellm import aembedding

            response = await aembedding(input=inputs, **params)
            return [item["embedding"] for item in response["data"]]
        except (ImportError, AttributeError):
            return await asyncio.to_thread(cls.embedding, alias, inputs, **overrides)
