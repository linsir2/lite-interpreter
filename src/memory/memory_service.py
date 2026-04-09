"""Memory-plane orchestration helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.blackboard import MemoryData, TaskMemorySummaryState, WorkspacePreferenceState, memory_blackboard
from src.skillnet.skill_retriever import SkillRetriever
from src.skillnet.skill_schema import SkillDescriptor
from src.storage.repository.memory_repo import MemoryRepo


@dataclass(frozen=True)
class MemoryRecallResult:
    """One staged memory recall/update result."""

    memory_data: MemoryData
    merged_skills: list[SkillDescriptor]
    new_matches: list[dict[str, Any]]


def _skill_name(value: Any) -> str:
    if hasattr(value, "name"):
        return str(value.name)
    if isinstance(value, dict):
        return str(value.get("name", ""))
    return ""


class MemoryService:
    """Coordinate task-scoped memory snapshots with durable workspace memories."""

    @staticmethod
    def _default_memory(
        *,
        tenant_id: str,
        task_id: str,
        workspace_id: str,
    ) -> MemoryData:
        return MemoryData(
            task_id=task_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            workspace_preferences=[
                WorkspacePreferenceState.model_validate(item)
                for item in MemoryRepo.list_workspace_preferences(tenant_id, workspace_id)
            ],
        )

    @classmethod
    def get_task_memory(
        cls,
        *,
        tenant_id: str,
        task_id: str,
        workspace_id: str,
    ) -> MemoryData:
        memory_data = memory_blackboard.read(tenant_id, task_id)
        if memory_data is None and memory_blackboard.restore(tenant_id, task_id):
            memory_data = memory_blackboard.read(tenant_id, task_id)
        if memory_data is not None:
            return memory_data
        return cls._default_memory(
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id=workspace_id,
        )

    @classmethod
    def persist_task_memory(cls, memory_data: MemoryData) -> MemoryData:
        memory_blackboard.write(memory_data.tenant_id, memory_data.task_id, memory_data)
        memory_blackboard.persist(memory_data.tenant_id, memory_data.task_id)
        return memory_data

    @staticmethod
    def _apply_repo_skill_update(memory_data: MemoryData, updated_skill: dict[str, Any] | None) -> None:
        if not updated_skill:
            return
        skill_name = _skill_name(updated_skill).strip()
        if not skill_name:
            return
        usage_payload = dict(updated_skill.get("usage", {}) or {})
        for skill in memory_data.approved_skills:
            if skill.name != skill_name:
                continue
            skill.usage = usage_payload
        for match in memory_data.historical_matches:
            if match.name != skill_name:
                continue
            match.usage = usage_payload

    @classmethod
    def recall_skills(
        cls,
        *,
        tenant_id: str,
        task_id: str,
        workspace_id: str,
        query: str,
        available_capabilities: list[str],
        stage: str,
        source_task_type: str | None = None,
        match_reason_detail: str,
        merged_limit: int = 5,
    ) -> MemoryRecallResult:
        memory_data = cls.get_task_memory(
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id=workspace_id,
        )
        task_local_skills = [item.model_dump(mode="json") for item in memory_data.approved_skills]
        historical_repo_skills = MemoryRepo.find_approved_skills(
            tenant_id,
            workspace_id,
            required_capabilities=SkillRetriever.infer_query_capabilities(query),
            source_task_type=source_task_type,
            limit=merged_limit,
        )
        preset_skills = SkillRetriever.load_preset_skills_for_query(
            query=query,
            available_capabilities=available_capabilities,
            source_task_type=source_task_type,
            limit=merged_limit,
        )
        historical_skills = SkillRetriever.merge_skill_sources(historical_repo_skills, preset_skills)
        ranked_historical_matches = SkillRetriever.rank_matches_for_query(
            historical_skills,
            query=query,
            available_capabilities=available_capabilities,
            source_task_type=source_task_type,
            limit=merged_limit,
        )
        merged_skills = SkillRetriever.merge_task_and_historical(
            task_local_skills,
            historical_skills,
            query=query,
            available_capabilities=available_capabilities,
            source_task_type=source_task_type,
            limit=merged_limit,
        )
        new_matches = SkillRetriever.extract_historical_matches(
            task_skills=task_local_skills,
            merged_skills=merged_skills,
            ranked_matches=ranked_historical_matches,
        )
        memory_data.approved_skills = [descriptor.to_payload() for descriptor in merged_skills]
        memory_data.historical_matches = SkillRetriever.merge_historical_match_updates(
            [item.model_dump(mode="json") for item in memory_data.historical_matches],
            new_matches,
            stage=stage,
            used_capabilities=SkillRetriever.infer_query_capabilities(query),
            match_reason_detail=match_reason_detail,
        )
        memory_data.workspace_preferences = [
            WorkspacePreferenceState.model_validate(item)
            for item in MemoryRepo.list_workspace_preferences(tenant_id, workspace_id)
        ]
        updated_usage_payloads: list[dict[str, Any]] = []
        for match in new_matches:
            updated_skill = MemoryRepo.record_skill_usage(
                tenant_id,
                workspace_id,
                _skill_name(match),
                task_id=task_id,
                stage=stage,
            )
            if updated_skill:
                updated_usage_payloads.append(updated_skill)
        for updated_skill in updated_usage_payloads:
            cls._apply_repo_skill_update(memory_data, updated_skill)
        cls.persist_task_memory(memory_data)
        return MemoryRecallResult(
            memory_data=memory_data,
            merged_skills=merged_skills,
            new_matches=new_matches,
        )

    @classmethod
    def mark_matches_used_in_codegen(
        cls,
        *,
        memory_data: MemoryData,
        query: str,
        merged_skills: list[SkillDescriptor],
    ) -> MemoryData:
        match_names_in_codegen = {
            descriptor.name
            for descriptor in merged_skills
            if descriptor.name in {_skill_name(item) for item in memory_data.historical_matches}
        }
        matches_for_stage: list[dict[str, Any]] = []
        for existing in memory_data.historical_matches:
            if _skill_name(existing) in match_names_in_codegen:
                matches_for_stage.append(existing.model_dump(mode="json"))
        memory_data.historical_matches = SkillRetriever.merge_historical_match_updates(
            [item.model_dump(mode="json") for item in memory_data.historical_matches],
            matches_for_stage,
            stage="coder",
            used_in_codegen=True,
            used_capabilities=SkillRetriever.infer_query_capabilities(query),
            match_reason_detail="coder incorporated historical skills into the code-generation payload",
        )
        skill_lookup = {descriptor.name: descriptor.to_payload() for descriptor in merged_skills}
        for match in memory_data.historical_matches:
            if not match.used_in_codegen:
                continue
            skill_payload = dict(skill_lookup.get(match.name, {}) or {})
            replay_case_ids = [
                str(case.get("case_id"))
                for case in (skill_payload.get("replay_cases", []) or [])
                if str(case.get("case_id", "")).strip()
            ]
            if replay_case_ids:
                match.used_replay_case_ids = replay_case_ids
            capabilities = [
                str(item) for item in (skill_payload.get("required_capabilities", []) or []) if str(item).strip()
            ]
            if capabilities:
                match.used_capabilities = capabilities
        return cls.persist_task_memory(memory_data)

    @classmethod
    def store_harvest_result(
        cls,
        *,
        tenant_id: str,
        task_id: str,
        workspace_id: str,
        harvested_candidates: list[dict[str, Any]],
        approved_skills: list[dict[str, Any]],
    ) -> MemoryData:
        memory_data = cls.get_task_memory(
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id=workspace_id,
        )
        memory_data.harvested_candidates = harvested_candidates
        merged_approved: dict[str, dict[str, Any]] = {
            _skill_name(item).strip(): item.model_dump(mode="json")
            for item in memory_data.approved_skills
            if _skill_name(item).strip()
        }
        for item in approved_skills:
            name = _skill_name(item).strip()
            if not name:
                continue
            merged_approved[name] = dict(item)
        memory_data.approved_skills = list(merged_approved.values())
        cls.persist_task_memory(memory_data)
        MemoryRepo.save_approved_skills(tenant_id, workspace_id, list(merged_approved.values()))
        return memory_data

    @staticmethod
    def build_task_summary(final_response: dict[str, Any] | None) -> TaskMemorySummaryState:
        payload = dict(final_response or {})
        return TaskMemorySummaryState(
            mode=str(payload.get("mode") or ""),
            headline=str(payload.get("headline") or ""),
            answer=str(payload.get("answer") or ""),
            key_findings=[str(item) for item in (payload.get("key_findings") or []) if str(item).strip()],
            evidence_refs=[str(item) for item in (payload.get("evidence_refs") or []) if str(item).strip()],
        )

    @classmethod
    def store_task_summary(
        cls,
        *,
        tenant_id: str,
        task_id: str,
        workspace_id: str,
        final_response: dict[str, Any] | None,
    ) -> MemoryData:
        memory_data = cls.get_task_memory(
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id=workspace_id,
        )
        memory_data.task_summary = cls.build_task_summary(final_response)
        cls.persist_task_memory(memory_data)
        MemoryRepo.save_task_summary(
            tenant_id,
            workspace_id,
            task_id,
            {
                "task_id": task_id,
                "tenant_id": tenant_id,
                "workspace_id": workspace_id,
                **memory_data.task_summary.model_dump(mode="json"),
            },
        )
        return memory_data
