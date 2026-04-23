#!/usr/bin/env python3
"""Create a real lite-interpreter analysis through the app-facing API."""

from __future__ import annotations

import argparse
import json
import sys

import httpx


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a lite-interpreter analysis over HTTP.")
    parser.add_argument("--api-base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--workspace-id", default="demo-workspace")
    parser.add_argument(
        "--question",
        default="请对比本月与上月利润表，说明利润下降和费用结构变化的主要原因。",
    )
    parser.add_argument("--access-token", default="")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    headers = {"Authorization": f"Bearer {args.access_token}"} if args.access_token else None
    response = httpx.post(
        f"{args.api_base_url.rstrip('/')}/api/app/analyses",
        json={
            "question": args.question,
            "assetIds": [],
            "workspaceId": args.workspace_id,
        },
        headers=headers,
        timeout=20.0,
    )
    response.raise_for_status()
    print(json.dumps(response.json(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
