"""
子黑板抽象基类

所有子黑板必须继承此类，实现固定接口
"""
from abc import ABC, abstractmethod
from typing import Any


class BaseSubBlackboard(ABC):
    """子黑板抽象基类"""
    # 子黑板唯一标识，必须在子类中定义，如 "execution" / "knowledge"
    board_name: str

    @abstractmethod
    def read(self, tenant_id: str, task_id: str) -> Any | None:
        """
        读数据，强制带租户ID做隔离

        :param tenant_id: 租户ID
        :param task_id: task_id
        :return: 数据值，不存在返回None
        """
        pass

    @abstractmethod
    def write(self, tenant_id: str, task_id: str, value: Any) -> bool:
        """
        写数据，强制带租户ID做隔
        离
        :param tenant_id: 租户ID
        :param task_id: task_id
        :param value: 数据值
        :return: 写入成功返回True
        """
        pass

    @abstractmethod
    def delete(self, tenant_id: str, task_id: str) -> bool:
        """
        删除数据

        :param tenant_id: 租户ID
        :param task_id: task_id
        :return: 删除成功返回True
        """
        pass

    @abstractmethod
    def persist(self, tenant_id: str, task_id: str) -> bool:
        """
        数据持久化到磁盘/数据库

        :param tenant_id: 租户ID
        :param task_id: 任务ID
        :return: 持久化成功返回True
        """
        pass

    @abstractmethod
    def restore(self, tenant_id: str, task_id: str) -> bool:
        """
        从持久化存储恢复数据

        :param tenant_id: 租户ID
        :param task_id: 任务ID
        :return: 恢复成功返回True
        """
        pass