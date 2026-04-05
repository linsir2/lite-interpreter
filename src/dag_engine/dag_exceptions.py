"""Typed exceptions for DAG orchestration failures."""
from __future__ import annotations


class DagEngineError(Exception):
    """Base exception for DAG orchestration failures."""


class DagRoutingError(DagEngineError):
    """Raised when the router cannot determine a valid next action."""


class DagExecutionError(DagEngineError):
    """Raised when a node in the DAG fails during execution."""
