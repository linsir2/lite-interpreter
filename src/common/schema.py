from enum import Enum

class EventTopic(str, Enum):
    """
    事件主题枚举：按「消费方+业务域+动作」分层命名，支持精准订阅
    命名规则：{消费方}.{业务域}.{动作}
    - 消费方：ui（前端）/ sys（系统内部）/ monitor（监控）
    - 业务域：task（任务）/ status（状态）/ artifact（产物）/ token（令牌）
    - 动作：created（创建）/ updated（更新）/ finished（完成）/ ready（就绪）/ cost（消耗）
    """
    # 前端感知类（UI 层订阅）
    UI_TASK_STATUS_UPDATE = "ui.task.status_update"  # 前端状态更新（替代原 STATUS_CHANGED）
    UI_TASK_CREATED = "ui.task.created"              # 前端感知任务创建（替代原 TASK_CREATED）
    UI_ARTIFACT_READY = "ui.artifact.ready"          # 前端感知产物（图表/文件）就绪
    UI_TASK_TRACE_UPDATE = "ui.task.trace_update"    # 前端感知动态链路流式轨迹
    UI_TASK_GOVERNANCE_UPDATE = "ui.task.governance_update"  # 前端感知治理 allow/deny 决策

    # 系统流转类（内部节点订阅）
    SYS_TASK_FINISHED = "sys.task.finished"          # 任务终态（成功/失败）
    SYS_TASK_RETRY = "sys.task.retry"                # 任务触发重试
    SYS_TOKEN_COST = "sys.token.cost"                # Token 消耗打点

    # 监控审计类（运维/计费订阅）
    MONITOR_TASK_ARCHIVED = "monitor.task.archived"  # 任务归档
    MONITOR_TASK_FAILED = "monitor.task.failed"      # 任务失败（告警用）
