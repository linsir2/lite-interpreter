#!/usr/bin/env python3
"""Trigger a demo task trace on the local lite-interpreter API."""

from __future__ import annotations

import argparse
import json

import httpx


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Trigger a fake task trace for SSE/UI demos.")
    parser.add_argument("--api-base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--task-id", default="demo-task-001")
    parser.add_argument("--tenant-id", default="demo-tenant")
    parser.add_argument("--workspace-id", default="demo-workspace")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    url = f"{args.api_base_url.rstrip('/')}/api/dev/tasks/{args.task_id}/demo-trace"
    response = httpx.post(
        url,
        json={
            "tenant_id": args.tenant_id,
            "workspace_id": args.workspace_id,
        },
        timeout=10.0,
    )
    response.raise_for_status()
    print(json.dumps(response.json(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
