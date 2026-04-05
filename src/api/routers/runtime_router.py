"""Runtime capability inspection endpoints."""
from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse

from src.dynamic_engine.runtime_registry import runtime_registry


async def list_runtimes(_request: Request) -> JSONResponse:
    manifests = runtime_registry.list_manifests()
    return JSONResponse(
        {
            "runtimes": [
                {
                    "runtime_id": manifest.runtime_id,
                    "display_name": manifest.display_name,
                    "description": manifest.description,
                    "runtime_modes": manifest.runtime_modes,
                    "domains": [
                        {
                            "domain_id": domain.domain_id,
                            "supported": domain.supported,
                        }
                        for domain in manifest.domains
                    ],
                    "limitations": manifest.limitations,
                }
                for manifest in manifests
            ]
        }
    )


async def get_runtime_capabilities(request: Request) -> JSONResponse:
    runtime_id = request.path_params["runtime_id"]
    try:
        manifest = runtime_registry.get_manifest(runtime_id)
    except KeyError:
        return JSONResponse({"error": "runtime not found", "runtime_id": runtime_id}, status_code=404)

    return JSONResponse(manifest.model_dump(mode="json"))
