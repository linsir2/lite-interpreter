"""KAG 顶层导出。"""

__all__ = ["KagBuilderOrchestrator", "QueryEngine"]


def __getattr__(name: str):
    if name == "KagBuilderOrchestrator":
        from .builder import KagBuilderOrchestrator

        return KagBuilderOrchestrator
    if name == "QueryEngine":
        from .retriever import QueryEngine

        return QueryEngine
    raise AttributeError(name)
