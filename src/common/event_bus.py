"""
异步事件总线：发布-订阅模式

- 非阻塞发布，后台异步推送给订阅者

- 支持按事件类型精准订阅

- 线程安全，支持多并发
"""
import asyncio
import contextlib
import datetime
import inspect
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Optional

from src.common.contracts import TraceEvent
from src.common.event_journal import event_journal
from src.common.logger import get_logger
from src.common.schema import EventTopic
from src.common.utils import generate_uuid
from src.privacy import mask_payload

logger = get_logger(__name__)

@dataclass
class Event:
    event_id: str
    topic: EventTopic # 事件类型
    tenant_id: str
    task_id: str
    workspace_id: str  # 🚀 新增：让事件具备空间隔离属性
    payload: dict[str, Any] # 事件上下文数据
    timestamp: datetime.datetime
    trace_id: str

    def to_trace_event(self) -> TraceEvent:
        return TraceEvent(
            event_id=self.event_id,
            topic=self.topic.value,
            tenant_id=self.tenant_id,
            task_id=self.task_id,
            workspace_id=self.workspace_id,
            trace_id=self.trace_id,
            timestamp=self.timestamp,
            payload=dict(self.payload),
        )

class AsyncEventBus:
    """异步事件总线单例"""
    _instance: Optional["AsyncEventBus"] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._init()
        return cls._instance
    
    def _init(self):
        """初始化"""
         # 订阅者映射：EventTopic -> 回调函数列表
        self._subscribers: dict[EventTopic, list[Callable[[Event], None]]] = {}
        # 全局订阅者：接收所有事件
        self._global_subscribers: list[Callable[[Event], None]] = []
        self._pending_puts: set[Any] = set()
        self._start_runtime()
        logger.info("异步事件总线初始化完成", extra={"trace_id": "system"})

    def _start_runtime(self) -> None:
        """Start or restart the background event loop runtime."""
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_ready = threading.Event()
        self._executor = threading.Thread(target=self._event_loop, daemon=True, name="EventBusLoop")
        self._event_queue: asyncio.Queue | None = None
        self._running = True
        self._processor_task: asyncio.Task | None = None

        self._executor.start()
        self._loop_ready.wait(timeout=5.0)
        if not self._loop_ready.is_set():
            raise RuntimeError("EventBus 后台线程启动超时")

    def ensure_running(self) -> None:
        """Ensure the event bus runtime is available after a prior stop()."""
        with self._lock:
            if self._running and self._loop and self._executor.is_alive():
                return
            self._pending_puts.clear()
            self._start_runtime()
            logger.info("事件总线运行时已重启", extra={"trace_id": "system"})

    def _event_loop(self):
        """后台事件循环"""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        
        # queue属于后台线程，不是主线程，要实现queue传递信息，需要跨线程
        self._event_queue = asyncio.Queue()
        # 启动事件处理协程
        self._processor_task = self._loop.create_task(self._process_events())
        # 由 loop 自己在真正开始处理回调后通知主线程
        self._loop.call_soon(self._loop_ready.set)
        # 运行事件循环直到收到停止信号
        try:
            self._loop.run_forever()
        finally:
            pending = [task for task in asyncio.all_tasks(self._loop) if not task.done()]
            for task in pending:
                task.cancel()
            if pending:
                with contextlib.suppress(Exception):
                    self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            self._loop.close()
    
    async def _process_events(self):
        """持续处理队列中的事件"""
        while self._running or (self._event_queue is not None and not self._event_queue.empty()):
            try:
                # 使用 asyncio.wait_for 支持优雅退出
                event = await asyncio.wait_for(self._event_queue.get(), timeout=1.0)
            except TimeoutError:
                # 如果超时，检查是否应该停止
                if not self._running:
                    break
                continue
            except asyncio.CancelledError:
                break

            try:
                await self._dispatch_event(event)
            except Exception as e:
                logger.error(f"事件处理异常: {str(e)}", extra={"trace_id": getattr(event, 'trace_id', 'system')})
            finally:
                self._event_queue.task_done()

    async def _dispatch_event(self, event: Event):
        """分发事件给所有订阅者"""
        # 将全局订阅者和特定事件订阅者合并处理
        with self._lock:
            callbacks = self._global_subscribers.copy()
            if event.topic in self._subscribers:
                callbacks.extend(self._subscribers[event.topic])
        
        pending_callbacks: list[tuple[Callable[[Event], None], asyncio.Task[Any]]] = []
        for callback in callbacks:
            try:
                if inspect.iscoroutinefunction(callback):
                    pending_callbacks.append((callback, asyncio.create_task(callback(event))))
                else:
                    callback(event)
            except Exception as e:
                logger.error(
                    f"事件分发失败 event={event.topic.value}, callback={getattr(callback, '__name__', repr(callback))}: {str(e)}",
                    extra={"trace_id": event.trace_id},
                )

        if not pending_callbacks:
            return

        results = await asyncio.gather(*(task for _, task in pending_callbacks), return_exceptions=True)
        for (callback, _), result in zip(pending_callbacks, results, strict=False):
            if isinstance(result, Exception):
                logger.error(
                    f"事件回调执行失败 event={event.topic.value}, callback={getattr(callback, '__name__', repr(callback))}: {result}",
                    extra={"trace_id": event.trace_id},
                )
    
    def publish(
        self,
        topic: EventTopic,
        tenant_id: str,
        task_id: str,
        workspace_id: str,
        payload: dict[str, Any],
        trace_id: str | None = None, 
    ) -> str:
        """
        发布事件（非阻塞）
        
        :return: 事件ID
        """
        trace_id = trace_id or generate_uuid()
        safe_payload, redaction_report = mask_payload(payload)
        if redaction_report["match_count"] and isinstance(safe_payload, dict):
            safe_payload = {
                **safe_payload,
                "_redaction": {
                    "match_count": redaction_report["match_count"],
                    "rule_hits": redaction_report["rule_hits"],
                },
            }
        event = Event(
            event_id=generate_uuid(),
            topic=topic,
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id=workspace_id,
            payload=safe_payload,
            timestamp=datetime.datetime.now(datetime.UTC),
            trace_id=trace_id,
        )
        try:
            self.ensure_running()
            if not self._running:
                raise RuntimeError("EventBus 已停止，无法继续发布事件")
            if not self._loop or self._event_queue is None:
                raise RuntimeError("EventBus 尚未初始化完成")
            event_journal.append(event.to_trace_event())
            put_future = asyncio.run_coroutine_threadsafe(self._event_queue.put(event), self._loop)
            with self._lock:
                self._pending_puts.add(put_future)
            put_future.add_done_callback(lambda future: self._discard_pending_put(future))
            logger.debug(
                f"事件发布成功 topic={topic.value}",
                extra={"trace_id": trace_id, "task_id": task_id},
            )
            return event.event_id
        except Exception as e:
            logger.error(
                f"事件发布失败 event_type={topic.value}: {str(e)}",
                extra={"trace_id": trace_id},
            )
            raise

    def _discard_pending_put(self, future: Any) -> None:
        with self._lock:
            self._pending_puts.discard(future)
    
    def subscribe(self, topic: EventTopic, callback: Callable[[Event], None]) -> None:
        """订阅指定类型的事件"""
        self.ensure_running()
        with self._lock:
            if topic not in self._subscribers:
                self._subscribers[topic] = []
            self._subscribers[topic].append(callback)
            logger.info(
                f"事件订阅成功 event_type={topic.value}",
                extra={"trace_id": "system"},
            )

    def unsubscribe(self, topic: EventTopic, callback: Callable[[Event], None]) -> None:
        """取消订阅指定类型的事件。"""
        with self._lock:
            callbacks = self._subscribers.get(topic)
            if not callbacks:
                return
            self._subscribers[topic] = [registered for registered in callbacks if registered is not callback]
            if not self._subscribers[topic]:
                self._subscribers.pop(topic, None)
            logger.info(
                f"事件取消订阅成功 event_type={topic.value}",
                extra={"trace_id": "system"},
            )
    
    def subscribe_all(self, callback: Callable[[Event], None]):
        """订阅所有事件（用于日志、监控"""
        self.ensure_running()
        with self._lock:
            self._global_subscribers.append(callback)
            logger.info(
                "全局事件订阅成功",
                extra={"trace_id": "system"},
            )

    def unsubscribe_all(self, callback: Callable[[Event], None]) -> None:
        """取消全局订阅。"""
        with self._lock:
            self._global_subscribers = [
                registered for registered in self._global_subscribers if registered is not callback
            ]
            logger.info(
                "全局事件取消订阅成功",
                extra={"trace_id": "system"},
            )
    
    def stop(self, timeout: float = 5.0):
        """停止事件总线（服务关闭时调用）"""
        if not self._loop or not self._executor.is_alive():
            self._running = False
            return

        self._running = False
        with self._lock:
            pending_puts = list(self._pending_puts)
        for future in pending_puts:
            with contextlib.suppress(Exception):
                future.result(timeout=timeout)
        if self._event_queue is not None:
            async def _shutdown() -> None:
                await self._event_queue.join()
                if self._processor_task and not self._processor_task.done():
                    self._processor_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await self._processor_task
                self._loop.stop()

            future = asyncio.run_coroutine_threadsafe(_shutdown(), self._loop)
            with contextlib.suppress(Exception):
                future.result(timeout=timeout)
        self._executor.join(timeout=timeout)
        logger.info("事件总线已停止", extra={"trace_id": "system"})


# 全局单例导出
event_bus = AsyncEventBus()
