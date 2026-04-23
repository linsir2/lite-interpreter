#!/usr/bin/env python3
"""Smoke-test the DeerFlow sidecar bridge client integration used by lite-interpreter."""

from __future__ import annotations

import argparse
import importlib
import os
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Smoke-test DeerFlow sidecar bridge client availability.")
    parser.add_argument(
        "--module",
        default=os.getenv("DEERFLOW_CLIENT_MODULE", "deerflow.client"),
        help="Python module path for DeerFlowClient (default: deerflow.client)",
    )
    parser.add_argument(
        "--config",
        default=os.getenv("DEERFLOW_CONFIG_PATH", str(Path(__file__).resolve().parents[1] / "config" / "deerflow_sidecar.yaml")),
        help="Optional DeerFlow sidecar config path",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("DEERFLOW_MODEL_NAME", ""),
        help="Optional DeerFlow model override",
    )
    parser.add_argument(
        "--run-chat",
        action="store_true",
        help="Run a minimal live chat after import + client init",
    )
    parser.add_argument(
        "--message",
        default="Analyze this paper for me",
        help="Prompt used when --run-chat is enabled",
    )
    parser.add_argument(
        "--thread-id",
        default="lite-interpreter-smoke",
        help="Thread id for chat smoke",
    )
    return parser


def print_status(label: str, value: str) -> None:
    print(f"[{label}] {value}")


def install_guidance() -> str:
    return (
        "Install DeerFlow from the official source package under "
        "`backend/packages/harness`, for example from a local checkout or a "
        "Git subdirectory install."
    )


def python_version_hint() -> str:
    return (
        f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro} "
        "(DeerFlow harness requires Python >= 3.12 according to its package metadata)"
    )


def main() -> int:
    args = build_parser().parse_args()
    print("DeerFlow bridge smoke")
    print("====================")
    print_status("module", args.module)
    print_status("config", args.config or "<none>")
    print_status("model", args.model or "<default>")
    print_status("python", python_version_hint())

    try:
        module = importlib.import_module(args.module)
    except Exception as exc:
        print_status("import", f"FAILED: {exc}")
        print_status("hint", install_guidance())
        return 1

    print_status("import", "OK")
    deerflow_client_cls = getattr(module, "DeerFlowClient", None)
    if deerflow_client_cls is None:
        print_status("client", "FAILED: module does not expose DeerFlowClient")
        return 1

    client_kwargs = {
        "thinking_enabled": True,
        "subagent_enabled": True,
        "plan_mode": True,
    }
    if args.config:
        config_path = Path(args.config)
        if not config_path.exists():
            print_status("config", f"FAILED: config path does not exist: {config_path}")
            return 1
        client_kwargs["config_path"] = str(config_path)
    if args.model:
        client_kwargs["model_name"] = args.model

    try:
        client = deerflow_client_cls(**client_kwargs)
    except Exception as exc:
        print_status("client", f"FAILED: {exc}")
        return 1

    print_status("client", "OK")

    if not args.run_chat:
        print_status("chat", "SKIPPED")
        print_status("result", "READY FOR LIVE CHAT")
        return 0

    try:
        response = client.chat(args.message, thread_id=args.thread_id)
    except Exception as exc:
        print_status("chat", f"FAILED: {exc}")
        return 1

    preview = response[:200].replace("\n", " ")
    print_status("chat", "OK")
    print_status("response", preview or "<empty>")
    print_status("result", "LIVE CHAT SUCCEEDED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
