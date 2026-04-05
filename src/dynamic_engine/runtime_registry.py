"""Registry for pluggable dynamic runtime backends."""
from __future__ import annotations

from typing import Callable

from src.common import RuntimeCapabilityManifest
from src.dynamic_engine.runtime_backends import DeerflowRuntimeBackend, DynamicRuntimeBackend


BackendFactory = Callable[..., DynamicRuntimeBackend]


class RuntimeRegistry:
    """Simple in-process registry for dynamic runtime backends."""

    def __init__(self) -> None:
        self._factories: dict[str, BackendFactory] = {}
        self._manifests: dict[str, RuntimeCapabilityManifest | Callable[[], RuntimeCapabilityManifest]] = {}

    def register(
        self,
        name: str,
        factory: BackendFactory,
        *,
        manifest: RuntimeCapabilityManifest | Callable[[], RuntimeCapabilityManifest] | None = None,
    ) -> None:
        normalized = str(name).strip().lower()
        self._factories[normalized] = factory
        if manifest is not None:
            self._manifests[normalized] = manifest

    def create(self, name: str, **kwargs) -> DynamicRuntimeBackend:
        normalized = str(name).strip().lower()
        if normalized not in self._factories:
            raise KeyError(f"Unknown dynamic runtime backend: {name}")
        return self._factories[normalized](**kwargs)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories.keys()))

    def get_manifest(self, name: str) -> RuntimeCapabilityManifest:
        normalized = str(name).strip().lower()
        if normalized not in self._factories:
            raise KeyError(f"Unknown dynamic runtime backend: {name}")
        manifest = self._manifests.get(normalized)
        if manifest is None:
            backend = self.create(normalized, max_steps=6)
            return backend.capability_manifest()
        return manifest() if callable(manifest) else manifest

    def list_manifests(self) -> list[RuntimeCapabilityManifest]:
        return [self.get_manifest(name) for name in self.names()]


runtime_registry = RuntimeRegistry()
runtime_registry.register(
    "deerflow",
    lambda **kwargs: DeerflowRuntimeBackend(**kwargs),
    manifest=lambda: DeerflowRuntimeBackend(max_steps=6).capability_manifest(),
)
