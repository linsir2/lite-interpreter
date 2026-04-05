"""Static coder node that emits sandbox-safe, dataset-aware analysis Python."""
from __future__ import annotations

from typing import Any, Dict

from src.blackboard.execution_blackboard import execution_blackboard
from src.blackboard.global_blackboard import global_blackboard
from src.blackboard.schema import GlobalStatus
from src.common import get_logger
from src.dag_engine.graphstate import DagGraphState
from src.dag_engine.nodes.static_codegen import (
    build_dataset_aware_code,
    build_static_coder_payload,
    build_static_input_mounts,
)
from src.skillnet.skill_retriever import SkillRetriever
from src.storage.repository.skill_repo import SkillRepo

logger = get_logger(__name__)


def coder_node(state: DagGraphState) -> Dict[str, Any]:
    tenant_id = state["tenant_id"]
    task_id = state["task_id"]

    global_blackboard.update_global_status(
        task_id=task_id,
        new_status=GlobalStatus.CODING,
        sub_status="正在生成静态链路代码",
    )

    exec_data = execution_blackboard.read(tenant_id, task_id)
    if not exec_data:
        logger.warning(f"[Coder] 缺少任务 {task_id} 的执行上下文")
        return {"generated_code": "", "next_actions": ["auditor"]}

    task_local_skills = list(exec_data.approved_skills or [])
    historical_repo_skills = SkillRepo.find_approved_skills(
        tenant_id,
        exec_data.workspace_id,
        required_capabilities=SkillRetriever.infer_query_capabilities(str(state.get("input_query", ""))),
        limit=5,
    )
    preset_skills = SkillRetriever.load_preset_skills_for_query(
        query=str(state.get("input_query", "")),
        available_capabilities=exec_data.task_envelope.allowed_tools if exec_data.task_envelope else [],
        limit=5,
    )
    historical_skills = SkillRetriever.merge_skill_sources(historical_repo_skills, preset_skills)
    ranked_historical_matches = SkillRetriever.rank_matches_for_query(
        historical_skills,
        query=str(state.get("input_query", "")),
        available_capabilities=exec_data.task_envelope.allowed_tools if exec_data.task_envelope else [],
        limit=5,
    )
    merged_skills = SkillRetriever.merge_task_and_historical(
        task_local_skills,
        historical_skills,
        query=str(state.get("input_query", "")),
        available_capabilities=exec_data.task_envelope.allowed_tools if exec_data.task_envelope else [],
        limit=5,
    )
    exec_data.approved_skills = [descriptor.to_payload() for descriptor in merged_skills]
    new_matches = SkillRetriever.extract_historical_matches(
        task_skills=task_local_skills,
        merged_skills=merged_skills,
        ranked_matches=ranked_historical_matches,
    )
    match_names_in_codegen = {
        descriptor.name
        for descriptor in merged_skills
        if descriptor.name in {str(item.get("name", "")) for item in exec_data.historical_skill_matches}
    }
    matches_for_stage = list(new_matches)
    for existing in exec_data.historical_skill_matches:
        if str(existing.get("name", "")) in match_names_in_codegen:
            matches_for_stage.append(dict(existing))
    exec_data.historical_skill_matches = SkillRetriever.merge_historical_match_updates(
        exec_data.historical_skill_matches,
        matches_for_stage,
        stage="coder",
        used_in_codegen=True,
        used_capabilities=SkillRetriever.infer_query_capabilities(str(state.get("input_query", ""))),
        match_reason_detail="coder incorporated historical skills into the code-generation payload",
    )
    skill_lookup = {
        str(skill.get("name", "")): dict(skill)
        for skill in exec_data.approved_skills
        if str(skill.get("name", "")).strip()
    }
    for match in exec_data.historical_skill_matches:
        if not match.get("used_in_codegen"):
            continue
        skill_payload = skill_lookup.get(str(match.get("name", "")), {})
        replay_case_ids = [
            str(case.get("case_id"))
            for case in (skill_payload.get("replay_cases", []) or [])
            if isinstance(case, dict) and str(case.get("case_id", "")).strip()
        ]
        if replay_case_ids:
            match["used_replay_case_ids"] = replay_case_ids
        capabilities = [str(item) for item in (skill_payload.get("required_capabilities", []) or []) if str(item).strip()]
        if capabilities:
            match["used_capabilities"] = capabilities
    for match in new_matches:
        SkillRepo.record_skill_usage(
            tenant_id,
            exec_data.workspace_id,
            str(match.get("name", "")),
            task_id=task_id,
            stage="coder",
        )

    input_mounts = build_static_input_mounts(exec_data)
    payload = build_static_coder_payload(
        exec_data=exec_data,
        state=state,
        input_mounts=input_mounts,
    )
    generated_code = build_dataset_aware_code(payload)
    exec_data.generated_code = generated_code
    execution_blackboard.write(tenant_id, task_id, exec_data)
    execution_blackboard.persist(tenant_id, task_id)
    return {"generated_code": generated_code, "input_mounts": input_mounts, "next_actions": ["auditor"]}
