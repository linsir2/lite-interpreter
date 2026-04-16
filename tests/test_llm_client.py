"""Tests for LiteLLM + DashScope client configuration."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.common.llm_client import LiteLLMClient, LiteLLMModelConfig


def test_litellm_client_loads_dashscope_aliases():
    config = LiteLLMClient.get_model_config("fast_model")
    assert config.params["api_base"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert config.params["model"].startswith("openai/")


def test_litellm_client_chat_uses_completion():
    fake_response = {"choices": [{"message": {"content": "ok"}}]}
    fake_module = SimpleNamespace(completion=lambda **_: fake_response)
    with patch.dict("sys.modules", {"litellm": fake_module}):
        content = LiteLLMClient.chat(
            "fast_model",
            [{"role": "user", "content": "hello"}],
        )
    assert content == "ok"


def test_litellm_client_achat_prefers_async_api():
    fake_response = {"choices": [{"message": {"content": "async-ok"}}]}
    fake_module = SimpleNamespace(
        acompletion=AsyncMock(return_value=fake_response),
        completion=lambda **_: {"choices": [{"message": {"content": "sync"}}]},
    )
    with patch.dict("sys.modules", {"litellm": fake_module}):
        content = asyncio.run(LiteLLMClient.achat("fast_model", [{"role": "user", "content": "hello"}]))
    assert content == "async-ok"


def test_litellm_client_aembedding_falls_back_to_thread():
    fake_module = SimpleNamespace()
    with patch.dict("sys.modules", {"litellm": fake_module}):
        with patch("src.common.llm_client.asyncio.to_thread", AsyncMock(return_value=[[0.1, 0.2]])) as mocked:
            result = asyncio.run(LiteLLMClient.aembedding("embedding_model", ["hello"]))
    assert result == [[0.1, 0.2]]
    assert mocked.called


def test_litellm_probe_alias_reports_config_without_live_call():
    status = LiteLLMClient.probe_alias("fast_model", live=False)
    assert status.alias == "fast_model"
    assert status.provider == "openai"
    assert status.configured is False or status.api_key_present is True


def test_litellm_probe_alias_reports_live_success():
    fake_config = LiteLLMModelConfig(alias="fast_model", params={"model": "openai/qwen-turbo", "api_key": "demo"})
    with patch.object(LiteLLMClient, "get_model_config", return_value=fake_config):
        with patch.object(LiteLLMClient, "chat", return_value="ok"):
            status = LiteLLMClient.probe_alias("fast_model", live=True)
    assert status.reachable is True
    assert status.smoke_ok is True
