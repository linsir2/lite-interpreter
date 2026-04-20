"""Capability registry for tools, skills, and runtime-facing actions."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field


# frozen=True 让实例变成不可变对象，适合定义元数据，防止运行时被修改
@dataclass(frozen=True)
class CapabilityDescriptor:
    """Normalized capability metadata used by governance and coordination."""

    capability_id: str
    category: str
    description: str
    aliases: tuple[str, ...] = ()
    risk_tags: tuple[str, ...] = ()
    network_access: str = "none"
    writes_state: bool = False
    executes_code: bool = False
    metadata: dict[str, object] = field(default_factory=dict)  # 防止多个实例底层共享同一个dict

    def matches(self, name: str) -> bool:
        lowered = str(name).strip().lower()
        if not lowered:
            return False
        return lowered == self.capability_id or lowered in self.aliases


class CapabilityRegistry:
    """In-memory registry with alias-aware lookup."""

    def __init__(self) -> None:
        self._capabilities: dict[str, CapabilityDescriptor] = {}

    def register(self, descriptor: CapabilityDescriptor) -> None:
        self._capabilities[descriptor.capability_id] = descriptor

    def get(self, name: str) -> CapabilityDescriptor | None:
        lowered = str(name).strip().lower()
        if not lowered:
            return None
        if lowered in self._capabilities:
            return self._capabilities[lowered]
        for descriptor in self._capabilities.values():
            if descriptor.matches(lowered):
                return descriptor
        return None

    def resolve_names(self, names: Iterable[str] | None) -> tuple[list[CapabilityDescriptor], list[str]]:
        resolved: list[CapabilityDescriptor] = []
        unknown: list[str] = []
        seen: set[str] = set()
        for name in names or []:  # 如果names为空，则遍历 [] (空列表)
            descriptor = self.get(name)
            if descriptor is None:
                normalized = str(name).strip()
                if normalized:
                    unknown.append(normalized)
                continue
            if descriptor.capability_id in seen:
                continue
            seen.add(descriptor.capability_id)
            resolved.append(descriptor)
        return resolved, unknown

    def normalize_names(self, names: Iterable[str] | None) -> list[str]:
        resolved, unknown = self.resolve_names(names)
        values = [descriptor.capability_id for descriptor in resolved]
        values.extend(str(name).strip() for name in unknown if str(name).strip())
        return values

    def all(self) -> tuple[CapabilityDescriptor, ...]:
        return tuple(sorted(self._capabilities.values(), key=lambda item: item.capability_id))


capability_registry = CapabilityRegistry()
capability_registry.register(
    CapabilityDescriptor(
        capability_id="web_search",
        category="research",
        description="Search external/public information sources.",
        aliases=("search", "internet_search"),
        risk_tags=("network", "external-data"),
        network_access="tool-mediated-only",
    )
)
capability_registry.register(
    CapabilityDescriptor(
        capability_id="web_fetch",
        category="research",
        description="Fetch and read a specific remote web resource.",
        aliases=("fetch", "http_fetch"),
        risk_tags=("network", "external-data"),
        network_access="tool-mediated-only",
    )
)
capability_registry.register(
    CapabilityDescriptor(
        capability_id="knowledge_query",
        category="knowledge",
        description="Query the KAG knowledge plane and return evidence packets.",
        aliases=("kag_query", "retrieval_query"),
        risk_tags=("knowledge",),
    )
)
capability_registry.register(
    CapabilityDescriptor(
        capability_id="sandbox_exec",
        category="execution",
        description="Execute generated code inside the local sandbox.",
        aliases=("sandbox_execute",),
        risk_tags=("execution", "stateful"),
        executes_code=True,
    )
)
capability_registry.register(
    CapabilityDescriptor(
        capability_id="dynamic_trace",
        category="control-plane",
        description="Write dynamic runtime trace events into the control plane.",
        aliases=("trace_write", "dynamic_trace_write"),
        risk_tags=("state-write", "trace"),
        writes_state=True,
    )
)
capability_registry.register(
    CapabilityDescriptor(
        capability_id="memory_sync",
        category="control-plane",
        description="Write structured patches back to the memory blackboard.",
        aliases=("memory_write", "memory_blackboard_sync"),
        risk_tags=("state-write", "memory"),
        writes_state=True,
    )
)
capability_registry.register(
    CapabilityDescriptor(
        capability_id="skill_admin",
        category="skills",
        description="Validate or authorize skill execution and skill promotion.",
        aliases=("skill_auth", "skill_validate"),
        risk_tags=("skills", "state-write"),
        writes_state=True,
    )
)
