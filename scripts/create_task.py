#!/usr/bin/env python3
"""Create a real lite-interpreter task through the local API."""

from __future__ import annotations

import argparse
import json
import sys

import httpx


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a lite-interpreter task over HTTP.")
    parser.add_argument("--api-base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--tenant-id", default="demo-tenant")
    parser.add_argument("--workspace-id", default="demo-workspace")
    parser.add_argument(
        "--query",
        default="帮我分析这份财报，并结合宏观经济数据预测下季度走势，自己找数据并写代码验证",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    response = httpx.post(
        f"{args.api_base_url.rstrip('/')}/api/tasks",
        json={
            "tenant_id": args.tenant_id,
            "workspace_id": args.workspace_id,
            "input_query": args.query,
            "autorun": True,
        },
        timeout=20.0,
    )
    response.raise_for_status()
    print(json.dumps(response.json(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
