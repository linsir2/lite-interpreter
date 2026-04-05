"""黑板核心逻辑测试用例"""
import asyncio
import pytest
import threading
from src.blackboard import (
    global_blackboard,
    execution_blackboard,
    knowledge_blackboard,
    GlobalStatus,
    ExecutionData,
)
from src.common import event_journal
from src.common.event_bus import AsyncEventBus, Event, event_bus
from src.common import EventTopic


@pytest.fixture(scope="function", autouse=True)
def init_blackboard():
    """测试前初始化黑板，注册子黑板"""
    global_blackboard.register_sub_board(execution_blackboard)
    global_blackboard.register_sub_board(knowledge_blackboard)
    event_bus._subscribers.clear()
    event_bus._global_subscribers.clear()
    event_journal.clear()
    yield
    # 测试后清理
    global_blackboard._task_states.clear()
    execution_blackboard._storage.clear()
    knowledge_blackboard._storage.clear()
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
        generated_code="print('hello world')",
        execution_result={"success": True, "output": "hello world"}
    )
    assert execution_blackboard.write(tenant_id, task_id, exec_data) is True
    
    # 读取数据
    read_data = execution_blackboard.read(tenant_id, task_id)
    assert read_data is not None
    assert read_data.generated_code == "print('hello world')"
    assert read_data.execution_result["success"] is True


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


def test_create_task_keeps_legacy_signature_compatibility():
    """兼容旧调用：只传 tenant_id + input_query。"""
    task_id = global_blackboard.create_task("legacy_tenant", "请分析利润波动")
    task = global_blackboard.get_task_state(task_id)
    assert task.workspace_id == "default_ws"
    assert task.input_query == "请分析利润波动"


def test_get_task_state_restores_from_persisted_global_state():
    task_id = global_blackboard.create_task("restore_tenant", "ws_restore", "恢复任务")
    global_blackboard.update_global_status(task_id, GlobalStatus.ANALYZING)

    global_blackboard._task_states.clear()

    restored = global_blackboard.get_task_state(task_id)
    assert restored.task_id == task_id
    assert restored.workspace_id == "ws_restore"
    assert restored.global_status == GlobalStatus.ANALYZING


def test_list_unfinished_tasks_includes_persisted_tasks():
    task_id = global_blackboard.create_task("unfinished_tenant", "ws_unfinished", "继续执行")
    global_blackboard.update_global_status(task_id, GlobalStatus.CODING)

    global_blackboard._task_states.clear()

    unfinished = global_blackboard.list_unfinished_tasks()
    assert any(task.task_id == task_id for task in unfinished)


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
