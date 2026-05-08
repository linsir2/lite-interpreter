"""黑板核心逻辑测试用例"""

import asyncio
import importlib
import threading
from datetime import timedelta

import pytest
from src.blackboard import (
    AuditResultState,
    DynamicRequestRuntimeState,
    DynamicRequestState,
    ExecutionData,
    GlobalStatus,
    InputMountState,
    KnowledgeData,
    MemoryData,
    execution_blackboard,
    global_blackboard,
    knowledge_blackboard,
    memory_blackboard,
)
from src.common import EventTopic, ExecutionRecord, event_journal
from src.common.event_bus import AsyncEventBus, Event, event_bus
from src.common.utils import get_utc_now
from src.storage.repository.state_repo import StateRepo


@pytest.fixture(scope="function", autouse=True)
def init_blackboard():
    """测试前初始化黑板，注册子黑板"""
    global_blackboard.register_sub_board(execution_blackboard)
    global_blackboard.register_sub_board(knowledge_blackboard)
    global_blackboard.register_sub_board(memory_blackboard)
    event_bus._subscribers.clear()
    event_bus._global_subscribers.clear()
    event_journal.clear()
    yield
    # 测试后清理
    global_blackboard._task_states.clear()
    execution_blackboard._storage.clear()
    knowledge_blackboard._storage.clear()
    memory_blackboard._storage.clear()
    event_bus._subscribers.clear()
    event_bus._global_subscribers.clear()
    event_journal.clear()


def test_task_create_and_status_update():
    """测试任务创建与状态更新"""
    # 1. 创建任务
    tenant_id = "test_tenant_001"
    workspace_id = "ws_test"
    input_query = "帮我分析销售数据"
    task_id = global_blackboard.create_task(tenant_id, workspace_id, input_query)

    # 2. 验证任务状态
    task = global_blackboard.get_task_state(task_id)
    assert task.tenant_id == tenant_id
    assert task.workspace_id == workspace_id
    assert task.input_query == input_query
    assert task.global_status == GlobalStatus.PENDING

    # 3. 更新状态
    global_blackboard.update_global_status(task_id, GlobalStatus.ANALYZING)
    task = global_blackboard.get_task_state(task_id)
    assert task.global_status == GlobalStatus.ANALYZING


def test_execution_blackboard_write_read():
    """测试执行流子黑板读写"""
    tenant_id = "test_tenant_001"
    task_id = "test_task_001"

    # 写入数据
    exec_data = ExecutionData(
        task_id=task_id,
        tenant_id=tenant_id,
        static={
            "generated_code": "print('hello world')",
            "execution_record": ExecutionRecord(
                session_id="session-test-001",
                tenant_id=tenant_id,
                workspace_id="default_ws",
                task_id=task_id,
                success=True,
                trace_id="trace-test-001",
                duration_seconds=0.1,
                output="hello world",
            ),
        },
    )
    assert execution_blackboard.write(tenant_id, task_id, exec_data) is True

    # 读取数据
    read_data = execution_blackboard.read(tenant_id, task_id)
    assert read_data is not None
    assert read_data.static.generated_code == "print('hello world')"
    assert read_data.static.execution_record is not None
    assert read_data.static.execution_record.success is True


def test_knowledge_blackboard_write_read():
    tenant_id = "test_tenant_knowledge"
    task_id = "test_task_knowledge"

    data = KnowledgeData(
        task_id=task_id,
        tenant_id=tenant_id,
        business_documents=[{"file_name": "rule.pdf", "status": "parsed", "parse_mode": "ocr"}],
        latest_retrieval_snapshot={"evidence_refs": ["chunk-1"]},
    )
    assert knowledge_blackboard.write(tenant_id, task_id, data) is True

    restored = knowledge_blackboard.read(tenant_id, task_id)
    assert restored is not None
    assert restored.business_documents[0].file_name == "rule.pdf"
    assert restored.parser_reports[0]["parse_mode"] == "ocr"


def test_memory_blackboard_write_read():
    tenant_id = "test_tenant_memory"
    task_id = "test_task_memory"

    data = MemoryData(
        task_id=task_id,
        tenant_id=tenant_id,
        approved_skills=[{"name": "skill-memory-demo"}],
        historical_matches=[{"name": "skill-history-demo", "selected_by_stages": ["router"]}],
        task_summary={"headline": "memory headline", "answer": "summary"},
    )
    assert memory_blackboard.write(tenant_id, task_id, data) is True

    restored = memory_blackboard.read(tenant_id, task_id)
    assert restored is not None
    assert restored.approved_skills[0].name == "skill-memory-demo"
    assert restored.historical_matches[0].name == "skill-history-demo"
    assert restored.task_summary.headline == "memory headline"


def test_execution_data_coerces_typed_audit_result():
    execution = ExecutionData(
        task_id="task-audit-typed",
        tenant_id="tenant-audit-typed",
        static={
            "audit_result": {
                "safe": True,
                "reason": "ok",
                "trace_id": "trace-audit",
                "duration_seconds": 0.01,
            }
        },
    )
    assert isinstance(execution.static.audit_result, AuditResultState)
    assert execution.static.audit_result.safe is True


def test_node_output_patch_coerces_typed_input_mounts():
    checkpoint = {
        "status": "completed",
        "output_patch": {
            "input_mounts": [
                {
                    "kind": "structured_dataset",
                    "host_path": "/tmp/in.csv",
                    "container_path": "/app/inputs/in.csv",
                    "file_name": "in.csv",
                    "encoding": "utf-8",
                    "sep": ",",
                }
            ],
            "audit_result": {
                "safe": True,
                "reason": "ok",
                "trace_id": "trace-checkpoint",
                "duration_seconds": 0.02,
            },
        },
    }
    execution = ExecutionData(
        task_id="task-checkpoint-typed",
        tenant_id="tenant-checkpoint-typed",
        control={"node_checkpoints": {"coder": checkpoint}},
    )
    output_patch = execution.control.node_checkpoints["coder"].output_patch
    assert isinstance(output_patch.input_mounts[0], InputMountState)
    assert output_patch.input_mounts[0].container_path == "/app/inputs/in.csv"
    assert isinstance(output_patch.audit_result, AuditResultState)
    assert output_patch.audit_result.safe is True


def test_execution_data_coerces_typed_dynamic_request():
    execution = ExecutionData(
        task_id="task-dynamic-request-typed",
        tenant_id="tenant-dynamic-request-typed",
        dynamic={
            "request": {
                "task_id": "task-dynamic-request-typed",
                "tenant_id": "tenant-dynamic-request-typed",
                "query": "继续调研",
                "sandbox_backend": "docker",
                "runtime": {
                    "runtime_mode": "sidecar",
                    "max_steps": 6,
                    "recursion_limit": 32,
                    "subagent_enabled": True,
                    "plan_mode": True,
                },
                "system_context": {"constraints": {"allowed_tools": ["knowledge_query"]}},
                "metadata": {"routing_mode": "dynamic"},
            },
        },
    )
    assert isinstance(execution.dynamic.request, DynamicRequestState)
    assert isinstance(execution.dynamic.request.runtime, DynamicRequestRuntimeState)
    assert execution.dynamic.request.runtime.runtime_mode == "sidecar"
    assert execution.dynamic.request.sandbox_backend == "docker"


def test_execution_data_coerces_strategy_and_artifact_contract_fields():
    execution = ExecutionData(
        task_id="task-strategy-typed",
        tenant_id="tenant-strategy-typed",
        static={
            "execution_strategy": {
                "analysis_mode": "hybrid_analysis",
                "research_mode": "single_pass",
                "strategy_family": "hybrid_reconciliation",
                "generator_id": "hybrid_reconciliation_generator",
                "evidence_plan": {
                    "research_mode": "single_pass",
                    "search_queries": ["行业平均增速"],
                    "allowed_domains": ["duckduckgo.com"],
                    "allowed_capabilities": ["web_search"],
                },
                },
                "program_spec": {
                    "spec_id": "hybrid:v1",
                    "strategy_family": "hybrid_reconciliation",
                    "analysis_mode": "hybrid_analysis",
                    "research_mode": "single_pass",
                    "steps": [{"step_id": "load:1", "kind": "load_evidence"}],
                    "artifact_emits": [
                        {
                            "artifact_key": "analysis_report",
                            "file_name": "analysis_report.md",
                            "emit_kind": "analysis_report",
                            "category": "report",
                        }
                    ],
                },
                "static_evidence_bundle": {
                    "request": {"query": "行业平均增速", "research_mode": "single_pass"},
                    "records": [{"title": "公开报告", "url": "https://example.com", "domain": "example.com"}],
                },
                "repair_plan": {
                    "reason": "missing required artifact",
                    "attempt_index": 1,
                    "action": "simplify_program",
                },
                "debug_attempts": [
                    {
                        "attempt_index": 1,
                        "reason": "missing required artifact",
                        "repair_plan": {
                            "reason": "missing required artifact",
                            "attempt_index": 1,
                            "action": "simplify_program",
                        },
                    }
                ],
                "generator_manifest": {
                    "generator_id": "hybrid_reconciliation_generator",
                    "strategy_family": "hybrid_reconciliation",
                "expected_artifact_keys": ["analysis_report"],
            },
            "artifact_verification": {
                "strategy_family": "hybrid_reconciliation",
                "passed": True,
                "verified_artifact_keys": ["analysis_report"],
            },
        },
        dynamic={
            "resume_overlay": {
                "continuation": "resume_static",
                "next_static_steps": ["analyst"],
                "evidence_refs": ["chunk-1"],
            }
        },
    )
    assert execution.static.execution_strategy is not None
    assert execution.static.execution_strategy.strategy_family == "hybrid_reconciliation"
    assert execution.static.execution_strategy.research_mode == "single_pass"
    assert execution.static.execution_strategy.evidence_plan.search_queries == ["行业平均增速"]
    assert execution.static.program_spec is not None
    assert execution.static.execution_strategy.artifact_plan.required_artifacts[0].file_name == "analysis_report.md"
    assert execution.static.execution_strategy.verification_plan is not None
    assert "analysis_report" in execution.static.execution_strategy.verification_plan.required_artifact_keys
    assert execution.static.static_evidence_bundle is not None
    assert execution.static.static_evidence_bundle.records[0].title == "公开报告"
    assert execution.static.repair_plan is not None
    assert execution.static.debug_attempts[0].repair_plan is not None
    assert execution.static.generator_manifest is not None
    assert execution.static.generator_manifest.expected_artifact_keys == ["analysis_report"]
    assert execution.static.artifact_verification is not None
    assert execution.static.artifact_verification.passed is True
    assert execution.dynamic.resume_overlay is not None
    assert execution.dynamic.resume_overlay.next_static_steps == ["analyst"]


def test_knowledge_list_workspace_states_prefers_newer_persisted_state_over_stale_memory():
    tenant_id = "tenant_projection_refresh"
    task_id = "task_projection_refresh"
    knowledge_blackboard.write(
        tenant_id,
        task_id,
        KnowledgeData(
            task_id=task_id,
            tenant_id=tenant_id,
            workspace_id="ws_projection_refresh",
            business_documents=[
                {
                    "file_name": "new-rule.pdf",
                    "path": "/tmp/new-rule.pdf",
                    "status": "parsed",
                }
            ],
            latest_retrieval_snapshot={"evidence_refs": ["chunk-new"]},
            updated_at=get_utc_now() - timedelta(days=1),
        ),
    )
    assert knowledge_blackboard.persist(tenant_id, task_id) is True

    full_state = StateRepo.load_blackboard_state(tenant_id, task_id)
    assert full_state is not None
    full_state["knowledge"] = {
        "task_id": task_id,
        "tenant_id": tenant_id,
        "workspace_id": "ws_projection_refresh",
        "business_documents": [
            {
                "file_name": "old-rule.pdf",
                "path": "/tmp/old-rule.pdf",
                "status": "pending",
            }
        ],
        "latest_retrieval_snapshot": {"evidence_refs": ["chunk-fresh"]},
        "updated_at": get_utc_now().isoformat(),
    }
    StateRepo.save_blackboard_state(tenant_id, task_id, "ws_projection_refresh", full_state)
    knowledge_blackboard._storage.clear()

    states = knowledge_blackboard.list_workspace_states(tenant_id, "ws_projection_refresh")

    assert len(states) == 1
    assert states[0].business_documents[0].file_name == "old-rule.pdf"
    assert states[0].latest_retrieval_snapshot.evidence_refs == ["chunk-fresh"]


def test_list_workspace_states_replaces_stale_in_memory_knowledge_with_newer_persisted_state():
    tenant_id = "tenant_projection_memory_refresh"
    task_id = "task_projection_memory_refresh"
    knowledge_blackboard.write(
        tenant_id,
        task_id,
        KnowledgeData(
            task_id=task_id,
            tenant_id=tenant_id,
            workspace_id="ws_projection_memory_refresh",
            business_documents=[
                {
                    "file_name": "stale-rule.pdf",
                    "path": "/tmp/stale-rule.pdf",
                    "status": "pending",
                }
            ],
            latest_retrieval_snapshot={"evidence_refs": ["chunk-stale"]},
            updated_at=get_utc_now() - timedelta(days=1),
        ),
    )
    StateRepo.save_blackboard_state(
        tenant_id,
        task_id,
        "ws_projection_memory_refresh",
        {
            "knowledge": {
                "task_id": task_id,
                "tenant_id": tenant_id,
                "workspace_id": "ws_projection_memory_refresh",
                "business_documents": [
                    {
                        "file_name": "fresh-rule.pdf",
                        "path": "/tmp/fresh-rule.pdf",
                        "status": "parsed",
                    }
                ],
                "latest_retrieval_snapshot": {"evidence_refs": ["chunk-fresh"]},
                "updated_at": get_utc_now().isoformat(),
            }
        },
    )

    states = knowledge_blackboard.list_workspace_states(tenant_id, "ws_projection_memory_refresh")

    assert len(states) == 1
    assert states[0].business_documents[0].file_name == "fresh-rule.pdf"
    assert states[0].latest_retrieval_snapshot.evidence_refs == ["chunk-fresh"]
    cached = knowledge_blackboard.read(tenant_id, task_id)
    assert cached is not None
    assert cached.business_documents[0].file_name == "fresh-rule.pdf"


def test_execution_list_workspace_states_prefers_newer_persisted_state_over_stale_memory():
    tenant_id = "tenant_execution_list_refresh"
    task_id = "task_execution_list_refresh"
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(
            task_id=task_id,
            tenant_id=tenant_id,
            workspace_id="ws_execution_list_refresh",
            control={
                "final_response": {"summary": "old"},
                "updated_at": (get_utc_now() - timedelta(days=1)).isoformat(),
            },
        ),
    )
    StateRepo.save_blackboard_state(
        tenant_id,
        task_id,
        "ws_execution_list_refresh",
        {
            "execution": {
                "task_id": task_id,
                "tenant_id": tenant_id,
                "workspace_id": "ws_execution_list_refresh",
                "control": {
                    "final_response": {"summary": "new"},
                    "updated_at": get_utc_now().isoformat(),
                },
            }
        },
    )

    states = execution_blackboard.list_workspace_states(tenant_id, "ws_execution_list_refresh")

    assert len(states) == 1
    assert states[0].control.final_response["summary"] == "new"


def test_event_bus_publish_subscribe():
    """测试事件总线发布订阅（优化版：同步等待）"""
    received_event = None
    expected_task_id = None
    # 1. 创建线程同步事件，替代 time.sleep
    event_received = threading.Event()

    # 订阅事件
    def callback(event):
        nonlocal received_event
        if event.task_id != expected_task_id:
            return
        if event.payload.get("new_status") != GlobalStatus.CODING.value:
            return
        received_event = event
        event_received.set()  # 回调执行完立即标记“已收到”

    event_bus.subscribe(EventTopic.UI_TASK_STATUS_UPDATE, callback)

    # 创建任务并更新状态
    task_id = global_blackboard.create_task("test_tenant", "default_ws", "test query")
    expected_task_id = task_id
    global_blackboard.update_global_status(task_id, GlobalStatus.CODING)

    # 2. 等待事件，最多等 2 秒，超时直接报错（比 sleep 更高效）
    assert event_received.wait(timeout=2.0), "超时未收到 STATUS_CHANGED 事件"

    # 3. 验证事件接收
    assert received_event is not None
    assert received_event.topic == EventTopic.UI_TASK_STATUS_UPDATE
    assert received_event.payload["new_status"] == GlobalStatus.CODING.value
    assert received_event.task_id == task_id  # 可以多加一层断言验证数据完整性

    journal_records = event_journal.read("test_tenant", task_id, workspace_id="default_ws")
    assert any(record["topic"] == EventTopic.UI_TASK_STATUS_UPDATE.value for record in journal_records)


def test_get_task_state_restores_from_persisted_global_state():
    task_id = global_blackboard.create_task("restore_tenant", "ws_restore", "恢复任务")
    global_blackboard.update_global_status(task_id, GlobalStatus.ANALYZING)

    global_blackboard._task_states.clear()

    restored = global_blackboard.get_task_state(task_id)
    assert restored.task_id == task_id
    assert restored.workspace_id == "ws_restore"
    assert restored.global_status == GlobalStatus.ANALYZING


def test_get_task_state_prefers_newer_persisted_global_state_over_stale_memory():
    task_id = global_blackboard.create_task("fresh_global_tenant", "ws_fresh_global", "刷新任务")
    task = global_blackboard.get_task_state(task_id)
    task.global_status = GlobalStatus.ANALYZING
    task.updated_at = get_utc_now() - timedelta(days=1)

    full_state = StateRepo.load_blackboard_state(task.tenant_id, task_id)
    assert full_state is not None
    full_state["global"]["global_status"] = GlobalStatus.SUCCESS.value
    full_state["global"]["sub_status"] = "已由其他实例更新"
    full_state["global"]["updated_at"] = get_utc_now().isoformat()
    StateRepo.save_blackboard_state(task.tenant_id, task_id, task.workspace_id, full_state)

    refreshed = global_blackboard.get_task_state(task_id)

    assert refreshed.global_status == GlobalStatus.SUCCESS
    assert refreshed.sub_status == "已由其他实例更新"


def test_list_unfinished_tasks_includes_persisted_tasks():
    task_id = global_blackboard.create_task("unfinished_tenant", "ws_unfinished", "继续执行")
    global_blackboard.update_global_status(task_id, GlobalStatus.CODING)

    global_blackboard._task_states.clear()

    unfinished = global_blackboard.list_unfinished_tasks()
    assert any(task.task_id == task_id for task in unfinished)


def test_list_unfinished_tasks_includes_harvesting_and_summarizing():
    harvesting_task = global_blackboard.create_task("unfinished_tenant_h", "ws_unfinished_h", "继续执行")
    summarizing_task = global_blackboard.create_task("unfinished_tenant_s", "ws_unfinished_s", "继续执行")
    global_blackboard.update_global_status(harvesting_task, GlobalStatus.HARVESTING)
    global_blackboard.update_global_status(summarizing_task, GlobalStatus.SUMMARIZING)

    global_blackboard._task_states.clear()

    unfinished = global_blackboard.list_unfinished_tasks()
    unfinished_ids = {task.task_id for task in unfinished}

    assert harvesting_task in unfinished_ids
    assert summarizing_task in unfinished_ids


def test_task_finished_payload_uses_explicit_repair_retry_semantics():
    task_id = global_blackboard.create_task("tenant-retry-payload", "ws-retry-payload", "query")
    global_blackboard.update_global_status(task_id, GlobalStatus.FAILED, current_retries=1)

    journal_records = event_journal.read("tenant-retry-payload", task_id, workspace_id="ws-retry-payload")
    finished_records = [record for record in journal_records if record["topic"] == EventTopic.SYS_TASK_FINISHED.value]

    assert finished_records
    payload = finished_records[-1]["payload"]
    assert payload["retry_info"]["scope"] == "codegen_debug_loop"
    assert payload["retry_info"]["used_repair_retries"] == 1
    assert "cost_info" not in payload


def test_event_bus_process_events_waits_for_dispatch_completion():
    callback_started = threading.Event()
    callback_finished = threading.Event()

    async def scenario():
        bus = object.__new__(AsyncEventBus)
        bus._subscribers = {}
        bus._global_subscribers = []
        bus._loop = asyncio.get_running_loop()
        bus._event_queue = asyncio.Queue()
        bus._running = True
        bus._processor_task = None
        bus._pending_puts = set()

        async def fake_dispatch(event):
            callback_started.set()
            await asyncio.sleep(0.1)
            callback_finished.set()
            bus._running = False

        bus._dispatch_event = fake_dispatch
        await bus._event_queue.put(
            Event(
                event_id="evt-test",
                topic=EventTopic.UI_TASK_STATUS_UPDATE,
                tenant_id="tenant-stop",
                task_id="task-stop",
                workspace_id="ws-stop",
                payload={"new_status": GlobalStatus.CODING.value},
                timestamp=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
                trace_id="trace-stop",
            )
        )

        processor = asyncio.create_task(bus._process_events())
        await bus._event_queue.join()
        await processor

    asyncio.run(scenario())

    assert callback_started.is_set()
    assert callback_finished.is_set()


def test_event_bus_can_restart_after_stop():
    bus = object.__new__(AsyncEventBus)
    AsyncEventBus._init(bus)
    try:
        bus.stop()
        bus.ensure_running()
        assert bus._running is True
        assert bus._executor.is_alive()
    finally:
        bus.stop()


def test_event_bus_dispatch_reports_async_callback_errors_with_correct_callback_name(monkeypatch):
    errors: list[str] = []
    event_bus_module = importlib.import_module("src.common.event_bus")

    def sync_callback(_event):
        return None

    async def async_callback(_event):
        raise RuntimeError("boom")

    bus = object.__new__(AsyncEventBus)
    bus._subscribers = {EventTopic.UI_TASK_STATUS_UPDATE: [sync_callback, async_callback]}
    bus._global_subscribers = []
    bus._lock = threading.Lock()

    monkeypatch.setattr(event_bus_module.logger, "error", lambda message, extra=None: errors.append(message))

    event = Event(
        event_id="evt-async-error",
        topic=EventTopic.UI_TASK_STATUS_UPDATE,
        tenant_id="tenant-async-error",
        task_id="task-async-error",
        workspace_id="ws-async-error",
        payload={"new_status": GlobalStatus.CODING.value},
        timestamp=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        trace_id="trace-async-error",
    )

    asyncio.run(bus._dispatch_event(event))

    assert errors
    assert errors[-1].count("async_callback") == 1
