#!/usr/bin/env python3
"""Smoke-test LiteLLM + DashScope chat and embedding configuration."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common.llm_client import LiteLLMClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Smoke-test DashScope-backed LiteLLM aliases.")
    parser.add_argument("--chat-alias", default="fast_model")
    parser.add_argument("--embedding-alias", default="embedding_model")
    parser.add_argument("--prompt", default="请用一句话介绍 lite-interpreter。")
    parser.add_argument("--embedding-text", default="lite-interpreter embedding smoke test")
    parser.add_argument("--run-chat", action="store_true")
    parser.add_argument("--run-embedding", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    print("DashScope / LiteLLM smoke")
    print("=========================")

    chat_cfg = LiteLLMClient.get_model_config(args.chat_alias)
    emb_cfg = LiteLLMClient.get_model_config(args.embedding_alias)
    print(
        json.dumps(
            {
                "chat_alias": args.chat_alias,
                "chat_model": chat_cfg.params.get("model"),
                "embedding_alias": args.embedding_alias,
                "embedding_model": emb_cfg.params.get("model"),
                "api_base": chat_cfg.params.get("api_base"),
                "has_dashscope_key": bool(os.getenv("DASHSCOPE_API_KEY")),
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    if not args.run_chat and not args.run_embedding:
        print("\nResult: CONFIG OK")
        return 0

    if not os.getenv("DASHSCOPE_API_KEY"):
        print("\nResult: SKIPPED (missing DASHSCOPE_API_KEY)")
        return 1

    if args.run_chat:
        content = LiteLLMClient.chat(
            args.chat_alias,
            [{"role": "user", "content": args.prompt}],
        )
        print("\nChat Result:")
        print(content[:400])

    if args.run_embedding:
        vectors = LiteLLMClient.embedding(args.embedding_alias, [args.embedding_text])
        print("\nEmbedding Result:")
        print({"vector_count": len(vectors), "vector_dim": len(vectors[0]) if vectors else 0})

    print("\nResult: LIVE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
