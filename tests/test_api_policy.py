"""Tests for harness policy management endpoints."""

from __future__ import annotations

import asyncio
import json

from src.api.routers.policy_router import get_harness_policy, update_harness_policy
from src.harness.policy import load_harness_policy
from starlette.requests import Request


def _make_request(path: str, *, body: dict | None = None) -> Request:
    payload = json.dumps(body or {}).encode()

    async def receive():
        return {"type": "http.request", "body": payload, "more_body": False}

    headers = [(b"content-type", b"application/json")] if body is not None else []
    return Request(
        {
            "type": "http",
            "method": "POST" if body is not None else "GET",
            "path": path,
            "query_string": b"",
            "path_params": {},
            "headers": headers,
        },
        receive=receive,
    )


def test_get_harness_policy_returns_policy(tmp_path, monkeypatch):
    policy_file = tmp_path / "policy.yaml"
    policy_file.write_text("mode: standard\nprofiles: {}\n", encoding="utf-8")
    monkeypatch.setattr("src.api.routers.policy_router.HARNESS_POLICY_PATH", policy_file)
    monkeypatch.setattr("src.harness.policy.HARNESS_POLICY_PATH", policy_file)
    monkeypatch.setattr("src.api.routers.policy_router.API_ENABLE_POLICY_API", True)

    load_harness_policy.cache_clear()
    response = asyncio.run(get_harness_policy(_make_request("/api/policy")))
    body = json.loads(response.body.decode())
    assert response.status_code == 200
    assert body["exists"] is True
    assert body["policy"]["mode"] == "standard"
    load_harness_policy.cache_clear()


def test_policy_api_is_disabled_by_default():
    response = asyncio.run(get_harness_policy(_make_request("/api/policy")))
    body = json.loads(response.body.decode())
    assert response.status_code == 404
    assert body["error"]["code"] == "ENDPOINT_DISABLED"
    assert body["error"]["message"] == "policy api disabled"


def test_update_harness_policy_persists_and_refreshes(tmp_path, monkeypatch):
    policy_file = tmp_path / "policy.yaml"
    policy_file.write_text("mode: standard\nprofiles: {}\n", encoding="utf-8")
    monkeypatch.setattr("src.api.routers.policy_router.HARNESS_POLICY_PATH", policy_file)
    monkeypatch.setattr("src.harness.policy.HARNESS_POLICY_PATH", policy_file)
    monkeypatch.setattr("src.api.routers.policy_router.API_ENABLE_POLICY_API", True)

    load_harness_policy.cache_clear()
    response = asyncio.run(
        update_harness_policy(
            _make_request(
                "/api/policy",
                body={"policy": {"mode": "core", "profiles": {}}},
            )
        )
    )
    body = json.loads(response.body.decode())
    assert response.status_code == 200
    assert body["updated"] is True
    assert body["policy"]["mode"] == "core"
    assert "mode: core" in policy_file.read_text(encoding="utf-8")
    load_harness_policy.cache_clear()


def test_update_harness_policy_rejects_missing_payload(tmp_path, monkeypatch):
    policy_file = tmp_path / "policy.yaml"
    monkeypatch.setattr("src.api.routers.policy_router.HARNESS_POLICY_PATH", policy_file)
    monkeypatch.setattr("src.harness.policy.HARNESS_POLICY_PATH", policy_file)
    monkeypatch.setattr("src.api.routers.policy_router.API_ENABLE_POLICY_API", True)

    response = asyncio.run(update_harness_policy(_make_request("/api/policy", body={})))
    body = json.loads(response.body.decode())

    assert response.status_code == 422
    assert body["error"] == "validation_error"


def test_update_harness_policy_rejects_non_mapping_yaml(tmp_path, monkeypatch):
    policy_file = tmp_path / "policy.yaml"
    monkeypatch.setattr("src.api.routers.policy_router.HARNESS_POLICY_PATH", policy_file)
    monkeypatch.setattr("src.harness.policy.HARNESS_POLICY_PATH", policy_file)
    monkeypatch.setattr("src.api.routers.policy_router.API_ENABLE_POLICY_API", True)

    response = asyncio.run(update_harness_policy(_make_request("/api/policy", body={"yaml": "- item"})))
    body = json.loads(response.body.decode())

    assert response.status_code == 400
    assert "mapping" in body["error"]
