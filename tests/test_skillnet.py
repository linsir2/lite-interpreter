"""SkillNet capability-aware harvesting tests."""

from __future__ import annotations

import json
import threading

import pytest
from src.blackboard import MemoryData, memory_blackboard
from src.blackboard.schema import ExecutionData
from src.mcp_gateway.tools.skill_auth_tool import SkillAuthTool
from src.memory import MemoryService
from src.skillnet.dynamic_skill_adapter import build_dynamic_skill_candidate
from src.skillnet.skill_harvester import SkillHarvester
from src.skillnet.skill_promoter import SkillPromoter
from src.skillnet.skill_retriever import SkillRetriever
from src.skillnet.skill_schema import SkillDescriptor, SkillPromotionStatus
from src.skillnet.skill_validator import SkillValidator
from src.storage.repository.memory_repo import MemoryRepo


def test_dynamic_skill_candidate_normalizes_required_capabilities():
    candidate = build_dynamic_skill_candidate(
        name="dynamic_skill_demo",
        source_task_type="dynamic_task",
        trace_records=[{"step_name": "research", "event_type": "completed"}],
        required_capabilities=["retrieval_query", "sandbox_execute"],
    )
    assert candidate.required_capabilities == ["knowledge_query", "sandbox_exec"]


def test_skill_harvester_derives_required_capabilities_from_governance():
    execution_data = ExecutionData(
        task_id="task-skill",
        tenant_id="tenant-skill",
        control={
            "task_envelope": {
                "task_id": "task-skill",
                "tenant_id": "tenant-skill",
                "workspace_id": "default_ws",
                "input_query": "dynamic task",
                "governance_profile": "researcher",
            },
            "execution_intent": {
                "intent": "dynamic_only",
                "destinations": ["dynamic_swarm"],
                "reason": "dynamic",
            },
            "decision_log": [
                {
                    "action": "dynamic_precheck",
                    "profile": "researcher",
                    "mode": "standard",
                    "allowed": True,
                    "risk_level": "low",
                    "risk_score": 0.1,
                    "allowed_tools": ["knowledge_query", "web_search"],
                }
            ],
        },
        dynamic={
            "summary": "done",
            "trace": [{"step_name": "research", "event_type": "completed"}],
        },
    )
    harvested = SkillHarvester.harvest(execution_data)
    assert harvested
    assert harvested[0]["required_capabilities"] == ["knowledge_query", "web_search"]
    assert harvested[0]["replay_cases"][0]["expected_signals"]
    assert harvested[0]["validation"]["valid"] is True


def test_skill_descriptor_round_trip_payload():
    descriptor = SkillDescriptor(
        name="skill_demo",
        description="demo",
        required_capabilities=["knowledge_query"],
        metadata={"summary": "demo"},
    )
    payload = descriptor.to_payload()
    restored = SkillDescriptor.from_payload(payload)
    assert restored.name == "skill_demo"
    assert restored.required_capabilities == ["knowledge_query"]


def test_skill_auth_tool_authorize_skill_uses_required_capabilities():
    result = SkillAuthTool.authorize_skill(
        skill=SkillDescriptor(
            name="skill_demo",
            required_capabilities=["knowledge_query", "sandbox_exec"],
        ),
        profile_name="reviewer",
    )
    assert result["skill_name"] == "skill_demo"
    assert result["allowed"] is False
    assert result["denied_capabilities"] == ["sandbox_exec"]


def test_skill_validator_marks_missing_capabilities_for_review():
    result = SkillValidator.validate(
        SkillDescriptor(
            name="skill_demo",
            required_capabilities=[],
        )
    )
    assert result["valid"] is False
    assert "missing required capabilities" in result["reasons"]


def test_skill_retriever_filters_by_available_capabilities():
    matches = SkillRetriever.filter_by_capabilities(
        [
            SkillDescriptor(name="skill_a", required_capabilities=["knowledge_query"]),
            SkillDescriptor(name="skill_b", required_capabilities=["sandbox_exec"]),
        ],
        available_capabilities=["retrieval_query", "dynamic_trace"],
    )
    assert [skill.name for skill in matches] == ["skill_a"]


def test_skill_promoter_marks_valid_and_authorized_skill_as_approved():
    promotion = SkillPromoter.evaluate(
        SkillDescriptor(
            name="skill_a",
            required_capabilities=["knowledge_query"],
            replay_cases=[],
            validation={"valid": True},
            metadata={"authorization": {"allowed": True}},
        )
    )
    assert promotion["status"] == SkillPromotionStatus.APPROVED.value
    assert promotion["ready_for_router"] is True


def test_skill_retriever_filters_approved_skills():
    skills = SkillRetriever.filter_approved(
        [
            SkillDescriptor(name="approved", promotion={"status": "approved"}),
            SkillDescriptor(name="review", promotion={"status": "needs_review"}),
        ]
    )
    assert [skill.name for skill in skills] == ["approved"]


def test_skill_promoter_adds_provenance():
    promotion = SkillPromoter.evaluate(
        SkillDescriptor(
            name="skill_a",
            validation={"valid": True, "status": "validated"},
            metadata={"authorization": {"allowed": True}},
        )
    )
    assert promotion["provenance"]["validation_status"] == "validated"
    assert promotion["provenance"]["authorization_allowed"] is True


def test_memory_repo_round_trip_in_memory():
    MemoryRepo.clear()
    MemoryRepo.save_approved_skills(
        "tenant_repo",
        "ws_repo",
        [{"name": "memory_repo_demo", "promotion": {"status": "approved"}}],
    )
    skills = MemoryRepo.list_approved_skills("tenant_repo", "ws_repo")
    assert skills[0]["name"] == "memory_repo_demo"


def test_memory_repo_find_approved_skills_filters_by_capability():
    MemoryRepo.clear()
    MemoryRepo.save_approved_skills(
        "tenant_repo_filter",
        "ws_repo_filter",
        [
            {"name": "skill_query", "required_capabilities": ["knowledge_query"], "promotion": {"status": "approved"}},
            {"name": "skill_exec", "required_capabilities": ["sandbox_exec"], "promotion": {"status": "approved"}},
        ],
    )
    skills = MemoryRepo.find_approved_skills(
        "tenant_repo_filter",
        "ws_repo_filter",
        required_capabilities=["knowledge_query"],
    )
    assert [skill["name"] for skill in skills] == ["skill_query"]


def test_memory_repo_records_usage_in_memory():
    MemoryRepo.clear()
    MemoryRepo.save_approved_skills(
        "tenant_repo_usage",
        "ws_repo_usage",
        [
            {
                "name": "skill_usage_demo",
                "required_capabilities": ["knowledge_query"],
                "promotion": {"status": "approved"},
            }
        ],
    )
    MemoryRepo.record_skill_usage(
        "tenant_repo_usage",
        "ws_repo_usage",
        "skill_usage_demo",
        task_id="task-usage",
        stage="router",
    )
    skill = MemoryRepo.list_approved_skills("tenant_repo_usage", "ws_repo_usage")[0]
    assert skill["usage"]["usage_count"] == 1
    assert skill["usage"]["last_task_id"] == "task-usage"


def test_memory_repo_usage_is_idempotent_for_same_task_and_stage():
    MemoryRepo.clear()
    MemoryRepo.save_approved_skills(
        "tenant_repo_usage_idem",
        "ws_repo_usage_idem",
        [
            {
                "name": "skill_usage_demo",
                "required_capabilities": ["knowledge_query"],
                "promotion": {"status": "approved"},
            }
        ],
    )
    MemoryRepo.record_skill_usage(
        "tenant_repo_usage_idem",
        "ws_repo_usage_idem",
        "skill_usage_demo",
        task_id="task-usage-idem",
        stage="router",
    )
    MemoryRepo.record_skill_usage(
        "tenant_repo_usage_idem",
        "ws_repo_usage_idem",
        "skill_usage_demo",
        task_id="task-usage-idem",
        stage="router",
    )
    skill = MemoryRepo.list_approved_skills("tenant_repo_usage_idem", "ws_repo_usage_idem")[0]
    assert skill["usage"]["usage_count"] == 1


def test_memory_repo_usage_idempotency_survives_memory_reset_with_postgres_payload(monkeypatch):
    MemoryRepo.clear()

    class _FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def fetchone(self):
            return self._rows[0] if self._rows else None

        def __iter__(self):
            return iter(self._rows)

    class _FakeConnection:
        def __init__(self, store):
            self.store = store

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params=None):
            query = str(sql)
            if isinstance(params, list):
                for item in params:
                    self.execute(sql, item)
                return _FakeResult([])
            params = params or {}
            key = (params.get("tenant_id"), params.get("workspace_id"), params.get("memory_key"))
            if "SELECT memory_payload, usage_count" in query:
                record = self.store.get(key)
                if not record:
                    return _FakeResult([])
                return _FakeResult([(json.dumps(record["payload"], ensure_ascii=False), record["usage_count"])])
            if "SELECT memory_payload" in query:
                rows = []
                for (tenant_id, workspace_id, _name), record in self.store.items():
                    if (
                        tenant_id == params.get("tenant_id")
                        and workspace_id == params.get("workspace_id")
                        and params.get("memory_kind") == "approved_skill"
                    ):
                        rows.append((json.dumps(record["payload"], ensure_ascii=False),))
                return _FakeResult(rows[: int(params.get("limit", len(rows) or 1))])
            if "INSERT INTO agent_memories" in query:
                payload = params["memory_payload"]
                record = self.store.setdefault(key, {"usage_count": 0, "payload": {}})
                record["usage_count"] = int(params["usage_count"])
                record["payload"] = json.loads(payload) if isinstance(payload, str) else payload
                return _FakeResult([])
            if "UPDATE agent_memories" in query:
                payload = params["memory_payload"]
                record = self.store.setdefault(key, {"usage_count": 0, "payload": {}})
                record["usage_count"] = int(params["usage_count"])
                record["payload"] = json.loads(payload) if isinstance(payload, str) else payload
                return _FakeResult([])
            raise AssertionError(f"Unexpected SQL: {query}")

    class _FakeEngine:
        def __init__(self, store):
            self.store = store

        def begin(self):
            return _FakeConnection(self.store)

        def connect(self):
            return _FakeConnection(self.store)

    fake_db = {
        ("tenant_repo_usage_pg", "ws_repo_usage_pg", "skill_usage_demo"): {
            "usage_count": 0,
            "payload": {
                "name": "skill_usage_demo",
                "required_capabilities": ["knowledge_query"],
                "promotion": {"status": "approved"},
            },
        }
    }

    monkeypatch.setattr("src.storage.repository.memory_repo.pg_client.engine", _FakeEngine(fake_db))
    monkeypatch.setattr("src.storage.repository.memory_repo.MemoryRepo._ensure_table", classmethod(lambda cls: None))

    MemoryRepo.record_skill_usage(
        "tenant_repo_usage_pg",
        "ws_repo_usage_pg",
        "skill_usage_demo",
        task_id="task-usage-pg",
        stage="router",
    )

    # 模拟进程重启：清空内存，只保留“数据库”中的 payload/usage。
    MemoryRepo.clear()

    MemoryRepo.record_skill_usage(
        "tenant_repo_usage_pg",
        "ws_repo_usage_pg",
        "skill_usage_demo",
        task_id="task-usage-pg",
        stage="router",
    )

    skills = MemoryRepo.list_approved_skills("tenant_repo_usage_pg", "ws_repo_usage_pg")
    assert fake_db[("tenant_repo_usage_pg", "ws_repo_usage_pg", "skill_usage_demo")]["usage_count"] == 1
    assert skills[0]["usage"]["usage_count"] == 1
    assert skills[0]["usage"]["last_task_id"] == "task-usage-pg"
    assert skills[0]["usage"]["last_stage"] == "router"


def test_memory_repo_does_not_publish_in_memory_new_value_when_postgres_write_fails(monkeypatch):
    MemoryRepo.clear()

    class _BrokenBeginConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params=None):  # noqa: ARG002
            raise RuntimeError("write failed")

    class _ReadOnlyConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params=None):
            query = str(sql)
            if "SELECT memory_payload" not in query:
                raise AssertionError(query)
            return [(json.dumps({"name": "old-skill", "promotion": {"status": "approved"}}, ensure_ascii=False),)]

    class _Engine:
        def begin(self):
            return _BrokenBeginConnection()

        def connect(self):
            return _ReadOnlyConnection()

    monkeypatch.setattr("src.storage.repository.memory_repo.pg_client.engine", _Engine())
    monkeypatch.setattr("src.storage.repository.memory_repo.MemoryRepo._ensure_table", classmethod(lambda cls: None))

    with pytest.raises(RuntimeError):
        MemoryRepo.save_approved_skills(
            "tenant_repo_fail",
            "ws_repo_fail",
            [{"name": "new-skill", "promotion": {"status": "approved"}}],
        )

    assert MemoryRepo._list_memory_records("tenant_repo_fail", "ws_repo_fail", memory_kind="approved_skill") == []


def test_memory_repo_strict_persistence_raises_on_write_failure(monkeypatch):
    MemoryRepo.clear()

    class _BrokenBeginConnection:
        def __enter__(self):
            raise RuntimeError("write failed")

        def __exit__(self, exc_type, exc, tb):
            return False

    class _Engine:
        def begin(self):
            return _BrokenBeginConnection()

    monkeypatch.setattr("src.storage.repository.memory_repo.pg_client.engine", _Engine())
    monkeypatch.setattr("src.storage.repository.memory_repo.MemoryRepo._ensure_table", classmethod(lambda cls: None))

    with pytest.raises(RuntimeError):
        MemoryRepo.save_approved_skills(
            "tenant_repo_fail_strict",
            "ws_repo_fail_strict",
            [{"name": "new-skill", "promotion": {"status": "approved"}}],
        )


def test_memory_repo_records_outcome_in_memory():
    MemoryRepo.clear()
    MemoryRepo.save_approved_skills(
        "tenant_repo_outcome",
        "ws_repo_outcome",
        [
            {
                "name": "skill_outcome_demo",
                "required_capabilities": ["knowledge_query"],
                "promotion": {"status": "approved"},
            }
        ],
    )
    MemoryRepo.record_skill_outcome(
        "tenant_repo_outcome",
        "ws_repo_outcome",
        "skill_outcome_demo",
        task_id="task-outcome",
        success=True,
    )
    skill = MemoryRepo.list_approved_skills("tenant_repo_outcome", "ws_repo_outcome")[0]
    assert skill["usage"]["success_count"] == 1
    assert skill["usage"]["failure_count"] == 0
    assert skill["usage"]["success_rate"] == 1.0


def test_memory_repo_usage_updates_survive_concurrent_in_memory_calls():
    MemoryRepo.clear()
    MemoryRepo.save_approved_skills(
        "tenant_repo_usage_concurrent",
        "ws_repo_usage_concurrent",
        [
            {
                "name": "skill_usage_demo",
                "required_capabilities": ["knowledge_query"],
                "promotion": {"status": "approved"},
            }
        ],
    )

    threads = [
        threading.Thread(
            target=lambda task_id=task_id: MemoryRepo.record_skill_usage(
                "tenant_repo_usage_concurrent",
                "ws_repo_usage_concurrent",
                "skill_usage_demo",
                task_id=task_id,
                stage="router",
            )
        )
        for task_id in ("task-a", "task-b")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    skill = MemoryRepo.list_approved_skills("tenant_repo_usage_concurrent", "ws_repo_usage_concurrent")[0]
    assert skill["usage"]["usage_count"] == 2


def test_memory_repo_outcome_updates_survive_concurrent_in_memory_calls():
    MemoryRepo.clear()
    MemoryRepo.save_approved_skills(
        "tenant_repo_outcome_concurrent",
        "ws_repo_outcome_concurrent",
        [
            {
                "name": "skill_outcome_demo",
                "required_capabilities": ["knowledge_query"],
                "promotion": {"status": "approved"},
            }
        ],
    )

    threads = [
        threading.Thread(
            target=lambda task_id=task_id, success=success: MemoryRepo.record_skill_outcome(
                "tenant_repo_outcome_concurrent",
                "ws_repo_outcome_concurrent",
                "skill_outcome_demo",
                task_id=task_id,
                success=success,
            )
        )
        for task_id, success in (("task-a", True), ("task-b", False))
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    skill = MemoryRepo.list_approved_skills("tenant_repo_outcome_concurrent", "ws_repo_outcome_concurrent")[0]
    assert skill["usage"]["success_count"] == 1
    assert skill["usage"]["failure_count"] == 1


def test_memory_repo_outcome_is_idempotent_for_same_task():
    MemoryRepo.clear()
    MemoryRepo.save_approved_skills(
        "tenant_repo_outcome_idem",
        "ws_repo_outcome_idem",
        [
            {
                "name": "skill_outcome_demo",
                "required_capabilities": ["knowledge_query"],
                "promotion": {"status": "approved"},
            }
        ],
    )
    MemoryRepo.record_skill_outcome(
        "tenant_repo_outcome_idem",
        "ws_repo_outcome_idem",
        "skill_outcome_demo",
        task_id="task-outcome-idem",
        success=True,
    )
    MemoryRepo.record_skill_outcome(
        "tenant_repo_outcome_idem",
        "ws_repo_outcome_idem",
        "skill_outcome_demo",
        task_id="task-outcome-idem",
        success=True,
    )
    skill = MemoryRepo.list_approved_skills("tenant_repo_outcome_idem", "ws_repo_outcome_idem")[0]
    assert skill["usage"]["success_count"] == 1
    assert skill["usage"]["failure_count"] == 0


def test_memory_service_recall_skills_refreshes_task_memory_usage():
    MemoryRepo.clear()
    memory_blackboard._storage.clear()
    MemoryRepo.save_approved_skills(
        "tenant_memory_usage_refresh",
        "ws_memory_usage_refresh",
        [
            {
                "name": "skill_usage_refresh",
                "required_capabilities": ["knowledge_query"],
                "promotion": {"status": "approved"},
            }
        ],
    )

    result = MemoryService.recall_skills(
        tenant_id="tenant_memory_usage_refresh",
        task_id="task_memory_usage_refresh",
        workspace_id="ws_memory_usage_refresh",
        query="请说明规则",
        available_capabilities=["knowledge_query"],
        stage="router",
        match_reason_detail="test refresh",
    )

    assert result.memory_data.historical_matches[0].usage.usage_count == 1
    assert result.memory_data.historical_matches[0].usage.last_stage == "router"


def test_memory_service_applies_outcome_updates_back_to_task_memory():
    from src.api.services.task_flow_service import _record_historical_skill_outcomes

    MemoryRepo.clear()
    memory_blackboard._storage.clear()
    MemoryRepo.save_approved_skills(
        "tenant_memory_outcome_refresh",
        "ws_memory_outcome_refresh",
        [
            {
                "name": "skill_outcome_refresh",
                "required_capabilities": ["knowledge_query"],
                "promotion": {"status": "approved"},
            }
        ],
    )
    memory_blackboard.write(
        "tenant_memory_outcome_refresh",
        "task_memory_outcome_refresh",
        MemoryData(
            task_id="task_memory_outcome_refresh",
            tenant_id="tenant_memory_outcome_refresh",
            workspace_id="ws_memory_outcome_refresh",
            historical_matches=[{"name": "skill_outcome_refresh", "used_in_codegen": True}],
        ),
    )
    memory_data = memory_blackboard.read("tenant_memory_outcome_refresh", "task_memory_outcome_refresh")
    assert memory_data is not None

    _record_historical_skill_outcomes(
        tenant_id="tenant_memory_outcome_refresh",
        workspace_id="ws_memory_outcome_refresh",
        task_id="task_memory_outcome_refresh",
        memory_data=memory_data,
        success=True,
    )

    refreshed = memory_blackboard.read("tenant_memory_outcome_refresh", "task_memory_outcome_refresh")
    assert refreshed is not None
    assert refreshed.historical_matches[0].usage.success_count == 1
