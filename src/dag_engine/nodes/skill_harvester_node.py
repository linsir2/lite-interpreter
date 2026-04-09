"""Skill harvesting node for both static and dynamic execution paths."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.blackboard.global_blackboard import global_blackboard
from src.blackboard.schema import GlobalStatus
from src.common import get_utc_now
from src.common.control_plane import task_governance_profile
from src.mcp_gateway import default_mcp_client
from src.mcp_gateway.tools.state_sync_tool import StateSyncTool
from src.memory import MemoryService
from src.skillnet.skill_harvester import SkillHarvester
from src.skillnet.skill_promoter import SkillPromoter
from src.skillnet.skill_retriever import SkillRetriever


def skill_harvester_node(state: Mapping[str, Any]) -> dict[str, Any]:
    tenant_id = str(state.get("tenant_id", ""))
    task_id = str(state.get("task_id", ""))

    global_blackboard.update_global_status(
        task_id=task_id,
        new_status=GlobalStatus.HARVESTING,
        sub_status="正在回收执行路径并沉淀技能候选",
    )

    patch = {
        "dynamic": {
            "request": state.get("dynamic_request"),
            "status": state.get("dynamic_status"),
            "summary": state.get("dynamic_summary"),
            "trace": state.get("dynamic_trace"),
            "trace_refs": state.get("dynamic_trace_refs"),
            "artifacts": state.get("dynamic_artifacts"),
            "recommended_static_skill": state.get("recommended_static_skill"),
        }
    }
    execution_data = StateSyncTool.sync_execution_patch(tenant_id, task_id, patch)
    harvested_candidates = SkillHarvester.harvest(execution_data)
    if harvested_candidates:
        authorized_candidates = []
        for candidate in harvested_candidates:
            candidate_copy = dict(candidate)
            candidate_copy["authorization"] = default_mcp_client.call_tool(
                "skill_auth",
                {
                    "skill": candidate_copy,
                    "profile_name": task_governance_profile(execution_data.control.task_envelope, "reviewer"),
                },
                context={"tenant_id": tenant_id, "task_id": task_id, "workspace_id": execution_data.workspace_id},
            )
            validation = dict(candidate_copy.get("validation", {}) or {})
            validation["authorization_allowed"] = bool(candidate_copy["authorization"].get("allowed"))
            candidate_copy["validation"] = validation
            metadata = dict(candidate_copy.get("metadata", {}) or {})
            metadata["authorization"] = dict(candidate_copy["authorization"])
            candidate_copy["metadata"] = metadata
            candidate_copy["promotion"] = SkillPromoter.evaluate(candidate_copy)
            candidate_copy["promotion"].update(
                {
                    "promoted_at": get_utc_now().isoformat(),
                    "source_task_id": task_id,
                    "source_trace_refs": list(state.get("dynamic_trace_refs") or []),
                }
            )
            authorized_candidates.append(candidate_copy)
        approved_skills = [
            descriptor.to_payload() for descriptor in SkillRetriever.filter_approved(authorized_candidates)
        ]
        MemoryService.store_harvest_result(
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id=execution_data.workspace_id,
            harvested_candidates=authorized_candidates,
            approved_skills=approved_skills,
        )

    return {}
