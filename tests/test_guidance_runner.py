from unittest.mock import patch

from src.runtime.guidance_runner import probe_guidance_runtime, run_route_selection


def test_probe_guidance_runtime_reports_capabilities():
    status = probe_guidance_runtime("fast_model")
    assert "package_importable" in status
    assert status["supports_roles"] is True
    assert "supports_select" in status


def test_run_route_selection_uses_guidance_when_available():
    with patch("src.runtime.guidance_runner._guidance_available", return_value=True):
        with patch(
            "src.runtime.guidance_runner._run_guidance_route_selection",
            return_value={"final_mode": "dynamic", "confidence": 0.9, "rationale": "research required"},
        ):
            result = run_route_selection("帮我分析财报并自己找数据", ["static", "dynamic"], "fast_model")

    assert result.backend == "guidance_openai"
    assert result.payload["final_mode"] == "dynamic"
    assert result.degraded is False


def test_run_route_selection_falls_back_to_litellm_json():
    with patch("src.runtime.guidance_runner._guidance_available", return_value=True):
        with patch("src.runtime.guidance_runner._run_guidance_route_selection", side_effect=RuntimeError("unsupported")):
            with patch(
                "src.runtime.guidance_runner._run_litellm_route_selection",
                return_value={"final_mode": "static", "confidence": 0.8, "rationale": "enough local context"},
            ):
                result = run_route_selection("请总结本地规则", ["static", "dynamic"], "fast_model")

    assert result.backend == "litellm_json"
    assert result.payload["final_mode"] == "static"
    assert result.degraded is True
