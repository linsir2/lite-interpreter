"""Tests for sandbox container lifecycle helpers."""
from __future__ import annotations

from pathlib import Path

from src.sandbox.container_lifecycle import collect_container_logs, prepare_sandbox_run


class _FakeContainer:
    def __init__(self, log_text: str) -> None:
        self._log_text = log_text

    def logs(self, tail: int = 1000):  # noqa: ARG002
        return self._log_text.encode("utf-8")


def test_prepare_sandbox_run_builds_output_dir_and_mounts(tmp_path):
    dataset_path = tmp_path / "sales.csv"
    dataset_path.write_text("region,amount\nsh,10\n", encoding="utf-8")

    prepared = prepare_sandbox_run(
        code="print('ok')",
        tenant_id="tenant-life",
        workspace_id="ws-life",
        trace_id="trace-life",
        input_mounts=[
            {
                "kind": "structured_dataset",
                "host_path": str(dataset_path),
                "container_path": "/app/inputs/sales.csv",
                "file_name": "sales.csv",
            }
        ],
    )

    assert prepared.host_output_dir.exists()
    assert prepared.code_file_path in prepared.volume_bindings
    assert str(dataset_path) in prepared.volume_bindings
    assert prepared.volume_bindings[str(dataset_path)]["bind"] == "/app/inputs/sales.csv"


def test_collect_container_logs_returns_text():
    container = _FakeContainer("hello sandbox")
    logs = collect_container_logs(container)
    assert logs == "hello sandbox"
