#!/usr/bin/env python3
"""Check whether the hybrid DAG + dynamic-swarm scaffolding is present."""

from __future__ import annotations

import sys
from pathlib import Path

REQUIRED_FILES = [
    Path("项目二.md"),
    Path("directory.txt"),
    Path("src/dag_engine/dag_graph.py"),
    Path("src/dag_engine/nodes/dynamic_swarm_node.py"),
    Path("src/dag_engine/nodes/skill_harvester_node.py"),
    Path("src/dynamic_engine/__init__.py"),
    Path("src/dynamic_engine/deerflow_bridge.py"),
    Path("src/dynamic_engine/blackboard_context.py"),
    Path("src/mcp_gateway/tools/dynamic_trace_tool.py"),
    Path("src/mcp_gateway/tools/state_sync_tool.py"),
    Path("src/skillnet/skill_harvester.py"),
    Path("src/skillnet/dynamic_skill_adapter.py"),
]


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    missing = [path for path in REQUIRED_FILES if not (repo_root / path).exists()]
    print("Hybrid readiness checklist")
    print("==========================")
    for path in REQUIRED_FILES:
        status = "OK" if path not in missing else "MISSING"
        print(f"[{status}] {path}")
    if missing:
        print("\nResult: NOT READY")
        return 1
    print("\nResult: READY")
    return 0


if __name__ == "__main__":
    sys.exit(main())
