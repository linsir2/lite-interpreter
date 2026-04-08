"""Simple retrieval helpers for capability-aware skill candidates."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from src.common import capability_registry
from src.skillnet.preset_skills import load_preset_skills
from src.skillnet.skill_schema import SkillDescriptor, SkillPromotionStatus


class SkillRetriever:
    """Filter harvested skills by required capabilities."""

    @staticmethod
    def infer_query_capabilities(query: str) -> list[str]:
        lowered = str(query).lower()
        requested: list[str] = []
        if any(token in lowered for token in ["规则", "口径", "制度", "合规", "知识", "policy", "metric"]):
            requested.append("knowledge_query")
        if any(token in lowered for token in ["执行", "验证", "run code", "写代码", "sandbox"]):
            requested.append("sandbox_exec")
        if any(token in lowered for token in ["联网", "research", "搜索", "外部", "fetch", "search"]):
            requested.extend(["web_search", "web_fetch"])
        if any(token in lowered for token in ["轨迹", "trace", "状态同步"]):
            requested.append("dynamic_trace")
        return capability_registry.normalize_names(requested)

    @staticmethod
    def filter_by_capabilities(
        skills: Iterable[SkillDescriptor | dict[str, Any]],
        available_capabilities: Iterable[str],
    ) -> list[SkillDescriptor]:
        available = set(capability_registry.normalize_names(available_capabilities))
        descriptors = [
            skill if isinstance(skill, SkillDescriptor) else SkillDescriptor.from_payload(dict(skill))
            for skill in skills
        ]
        return [
            descriptor
            for descriptor in descriptors
            if set(descriptor.required_capabilities).issubset(available)
        ]

    @staticmethod
    def filter_approved(skills: Iterable[SkillDescriptor | dict[str, Any]]) -> list[SkillDescriptor]:
        descriptors = [
            skill if isinstance(skill, SkillDescriptor) else SkillDescriptor.from_payload(dict(skill))
            for skill in skills
        ]
        return [
            descriptor
            for descriptor in descriptors
            if str((descriptor.promotion or {}).get("status", "")) == SkillPromotionStatus.APPROVED.value
        ]

    @staticmethod
    def rank_for_query(
        skills: Iterable[SkillDescriptor | dict[str, Any]],
        *,
        query: str,
        available_capabilities: Iterable[str] | None = None,
        source_task_type: str | None = None,
        limit: int = 5,
    ) -> list[SkillDescriptor]:
        ranked_matches = SkillRetriever.rank_matches_for_query(
            skills,
            query=query,
            available_capabilities=available_capabilities,
            source_task_type=source_task_type,
            limit=limit,
        )
        return [match["descriptor"] for match in ranked_matches]

    @staticmethod
    def rank_matches_for_query(
        skills: Iterable[SkillDescriptor | dict[str, Any]],
        *,
        query: str,
        available_capabilities: Iterable[str] | None = None,
        source_task_type: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        descriptors = SkillRetriever.filter_approved(skills)
        available = set(capability_registry.normalize_names(available_capabilities or []))
        desired = set(SkillRetriever.infer_query_capabilities(query))
        query_terms = {term for term in str(query).lower().replace("，", " ").replace(",", " ").split() if term}

        scored: list[tuple[int, SkillDescriptor, str]] = []
        for descriptor in descriptors:
            score = 0
            reasons: list[str] = []
            required = set(descriptor.required_capabilities)
            recommended = descriptor.metadata.get("recommended", {}) if isinstance(descriptor.metadata, Mapping) else {}
            if source_task_type and recommended.get("source_task_type") == source_task_type:
                score += 3
                reasons.append(f"source_task_type={source_task_type}")
            if desired:
                desired_hits = required.intersection(desired)
                score += len(desired_hits) * 3
                if desired_hits:
                    reasons.append(f"query_capabilities={','.join(sorted(desired_hits))}")
            if available:
                available_hits = required.intersection(available)
                score += len(available_hits) * 2
                if available_hits:
                    reasons.append(f"available_capabilities={','.join(sorted(available_hits))}")
            haystack = " ".join(
                [
                    descriptor.name.lower(),
                    descriptor.description.lower(),
                    " ".join(str(item).lower() for item in recommended.values()),
                ]
            )
            text_hits = sum(1 for term in query_terms if term and term in haystack)
            score += text_hits
            if text_hits:
                reasons.append(f"text_hits={text_hits}")
            if score > 0:
                scored.append((score, descriptor, " | ".join(reasons) if reasons else "generic_match"))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            {
                "descriptor": descriptor,
                "match_score": score,
                "match_reason": reason,
                "match_source": str(descriptor.metadata.get("match_source") or "historical_repo"),
            }
            for score, descriptor, reason in scored[:limit]
        ]

    @staticmethod
    def load_preset_skills_for_query(
        *,
        query: str,
        available_capabilities: Iterable[str] | None = None,
        source_task_type: str | None = None,
        limit: int = 5,
    ) -> list[SkillDescriptor]:
        presets = []
        for descriptor in load_preset_skills():
            payload = descriptor.to_payload()
            payload["metadata"] = {
                **dict(payload.get("metadata", {}) or {}),
                "match_source": "preset_seed",
            }
            presets.append(SkillDescriptor.from_payload(payload))
        return SkillRetriever.rank_for_query(
            presets,
            query=query,
            available_capabilities=available_capabilities,
            source_task_type=source_task_type,
            limit=limit,
        )

    @staticmethod
    def merge_skill_sources(
        *sources: Iterable[SkillDescriptor | dict[str, Any]],
    ) -> list[SkillDescriptor]:
        merged: list[SkillDescriptor] = []
        seen: set[str] = set()
        for source in sources:
            for skill in source:
                descriptor = skill if isinstance(skill, SkillDescriptor) else SkillDescriptor.from_payload(dict(skill))
                if descriptor.name in seen:
                    continue
                seen.add(descriptor.name)
                merged.append(descriptor)
        return merged

    @staticmethod
    def merge_task_and_historical(
        task_skills: Iterable[SkillDescriptor | dict[str, Any]],
        historical_skills: Iterable[SkillDescriptor | dict[str, Any]],
        *,
        query: str,
        available_capabilities: Iterable[str] | None = None,
        source_task_type: str | None = None,
        limit: int = 5,
    ) -> list[SkillDescriptor]:
        task_descriptors = [
            skill if isinstance(skill, SkillDescriptor) else SkillDescriptor.from_payload(dict(skill))
            for skill in task_skills
        ]
        ranked_historical_matches = SkillRetriever.rank_matches_for_query(
            historical_skills,
            query=query,
            available_capabilities=available_capabilities,
            source_task_type=source_task_type,
            limit=limit,
        )
        ranked_historical = [match["descriptor"] for match in ranked_historical_matches]
        if not ranked_historical:
            ranked_historical = SkillRetriever.filter_approved(historical_skills)[:limit]
        merged: list[SkillDescriptor] = []
        seen: set[str] = set()
        for descriptor in list(task_descriptors) + list(ranked_historical):
            if descriptor.name in seen:
                continue
            seen.add(descriptor.name)
            merged.append(descriptor)
            if len(merged) >= limit:
                break
        return merged

    @staticmethod
    def extract_historical_matches(
        *,
        task_skills: Iterable[SkillDescriptor | dict[str, Any]],
        merged_skills: Iterable[SkillDescriptor | dict[str, Any]],
        ranked_matches: Iterable[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        task_names = {
            (skill.name if isinstance(skill, SkillDescriptor) else SkillDescriptor.from_payload(dict(skill)).name)
            for skill in task_skills
        }
        ranked_by_name = {
            str(match.get("descriptor").name if isinstance(match.get("descriptor"), SkillDescriptor) else ""): match
            for match in (ranked_matches or [])
            if match.get("descriptor")
        }
        matches: list[dict[str, Any]] = []
        for skill in merged_skills:
            descriptor = skill if isinstance(skill, SkillDescriptor) else SkillDescriptor.from_payload(dict(skill))
            if descriptor.name in task_names:
                continue
            ranked = ranked_by_name.get(descriptor.name, {})
            matches.append(
                {
                    "name": descriptor.name,
                    "required_capabilities": list(descriptor.required_capabilities),
                    "promotion": dict(descriptor.promotion),
                    "usage": dict(descriptor.metadata.get("usage", {}) or {}) if isinstance(descriptor.metadata, Mapping) else {},
                    "match_source": str(ranked.get("match_source") or "historical_repo"),
                    "match_reason": str(ranked.get("match_reason") or "historical_match"),
                    "match_score": int(ranked.get("match_score") or 0),
                    "selected_by_stages": [],
                    "selected_by_stage_details": [],
                    "used_in_codegen": False,
                    "used_replay_case_ids": [],
                    "used_capabilities": [],
                }
            )
        return matches

    @staticmethod
    def merge_historical_match_updates(
        existing_matches: Iterable[dict[str, Any]],
        new_matches: Iterable[dict[str, Any]],
        *,
        stage: str,
        used_in_codegen: bool = False,
        used_replay_case_ids: Iterable[str] | None = None,
        used_capabilities: Iterable[str] | None = None,
        match_reason_detail: str | None = None,
    ) -> list[dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {
            str(item.get("name", "")): dict(item)
            for item in existing_matches
            if str(item.get("name", "")).strip()
        }
        replay_case_ids = [str(item) for item in (used_replay_case_ids or []) if str(item).strip()]
        capability_ids = [str(item) for item in capability_registry.normalize_names(used_capabilities or []) if str(item).strip()]
        for match in new_matches:
            name = str(match.get("name", "")).strip()
            if not name:
                continue
            current = merged.get(name, {})
            updated = dict(current)
            updated.update(dict(match))
            stages = list(updated.get("selected_by_stages", []) or [])
            if stage and stage not in stages:
                stages.append(stage)
            updated["selected_by_stages"] = stages
            stage_details = list(updated.get("selected_by_stage_details", []) or [])
            if stage:
                detail = {
                    "stage": stage,
                    "reason": match_reason_detail or str(updated.get("match_reason") or ""),
                }
                if replay_case_ids:
                    detail["used_replay_case_ids"] = list(replay_case_ids)
                if capability_ids:
                    detail["used_capabilities"] = list(capability_ids)
                if detail not in stage_details:
                    stage_details.append(detail)
            updated["selected_by_stage_details"] = stage_details
            updated["used_in_codegen"] = bool(updated.get("used_in_codegen")) or used_in_codegen
            existing_replay = list(updated.get("used_replay_case_ids", []) or [])
            for item in replay_case_ids:
                if item not in existing_replay:
                    existing_replay.append(item)
            updated["used_replay_case_ids"] = existing_replay
            existing_capabilities = list(updated.get("used_capabilities", []) or [])
            for item in capability_ids:
                if item not in existing_capabilities:
                    existing_capabilities.append(item)
            updated["used_capabilities"] = existing_capabilities
            merged[name] = updated
        return [item for item in merged.values() if item.get("name")]
