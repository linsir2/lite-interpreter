"""Section renderers for the analysis workspace."""

from __future__ import annotations

from typing import Any


def render_analysis_body(
    st: Any,
    *,
    sections: dict[str, list[Any]],
    build_output_cards: Any,
    describe_output_asset: Any,
    find_artifact_reference: Any,
    fetch_execution_artifact_bytes: Any,
    list_directory_entries: Any,
    task_result: dict[str, Any],
    api_base_url: str,
    tenant_id: str,
    workspace_id: str,
    api_token: str,
    task_id: str,
) -> None:
    info_col1, info_col2 = st.columns(2)
    with info_col1:
        st.markdown("#### Analysis Question")
        analysis_brief = sections["analysis_brief"][0] if sections["analysis_brief"] else {}
        if analysis_brief.get("question"):
            st.write(str(analysis_brief.get("question")))
        else:
            st.caption("No explicit analysis question recorded.")

        st.markdown("#### Key Findings")
        if sections["findings"]:
            for item in sections["findings"]:
                st.markdown(f"- {item}")
        else:
            st.caption("No key findings recorded.")

        st.markdown("#### Evidence")
        if sections["evidence_refs"]:
            for ref in sections["evidence_refs"]:
                st.code(ref, language=None)
        else:
            st.caption("No evidence refs recorded.")

        st.markdown("#### Data And Rules")
        if analysis_brief:
            if analysis_brief.get("analysis_mode"):
                st.caption(f"mode={analysis_brief.get('analysis_mode')}")
            dataset_summaries = analysis_brief.get("dataset_summaries", []) or []
            if dataset_summaries:
                st.markdown("**Datasets**")
                for item in dataset_summaries:
                    st.caption(str(item))
            business_rules = analysis_brief.get("business_rules", []) or []
            business_metrics = analysis_brief.get("business_metrics", []) or []
            business_filters = analysis_brief.get("business_filters", []) or []
            if business_rules or business_metrics or business_filters:
                st.markdown("**Business Context**")
                for item in business_rules[:3]:
                    st.caption(f"rule: {item}")
                for item in business_metrics[:3]:
                    st.caption(f"metric: {item}")
                for item in business_filters[:3]:
                    st.caption(f"filter: {item}")
            known_gaps = analysis_brief.get("known_gaps", []) or []
            if known_gaps:
                st.markdown("**Known Gaps**")
                for item in known_gaps:
                    st.caption(str(item))
            if analysis_brief.get("recommended_next_step"):
                st.caption(f"next={analysis_brief.get('recommended_next_step')}")
        else:
            st.caption("No analysis brief recorded.")

        st.markdown("#### Knowledge Snapshot")
        knowledge_snapshot = sections["knowledge_snapshot"][0] if sections["knowledge_snapshot"] else {}
        if knowledge_snapshot:
            rewritten_query = knowledge_snapshot.get("rewritten_query")
            if rewritten_query:
                st.caption(f"rewritten_query={rewritten_query}")
            recall_strategies = knowledge_snapshot.get("recall_strategies", []) or []
            if recall_strategies:
                st.caption(f"recall={', '.join(str(item) for item in recall_strategies)}")
            filters = knowledge_snapshot.get("filters", {}) or {}
            if filters:
                st.caption(f"filters={filters}")
            metadata = knowledge_snapshot.get("metadata", {}) or {}
            if metadata:
                st.caption(str(metadata))
        else:
            st.caption("No knowledge snapshot recorded.")

        st.markdown("#### Compiled Knowledge")
        compiled_knowledge = sections["compiled_knowledge"][0] if sections["compiled_knowledge"] else {}
        if compiled_knowledge:
            rule_specs = compiled_knowledge.get("rule_specs", []) or []
            metric_specs = compiled_knowledge.get("metric_specs", []) or []
            filter_specs = compiled_knowledge.get("filter_specs", []) or []
            parse_errors = compiled_knowledge.get("spec_parse_errors", []) or []
            graph_summary = compiled_knowledge.get("graph_compilation_summary", {}) or {}
            st.caption(
                "rules="
                f"{len(rule_specs)} metrics={len(metric_specs)} filters={len(filter_specs)} "
                f"parse_errors={len(parse_errors)}"
            )
            if graph_summary:
                st.caption(
                    "graph "
                    f"candidates={graph_summary.get('candidate_count', 0)} "
                    f"accepted={graph_summary.get('accepted_count', 0)} "
                    f"rejected={graph_summary.get('rejected_count', 0)}"
                )
                reject_reasons = graph_summary.get("reject_reasons", {}) or {}
                if reject_reasons:
                    st.caption(f"reject_reasons={reject_reasons}")
            for item in rule_specs[:3]:
                st.caption(f"rule_spec: {item.get('source_text') or item.get('normalized_text')}")
            for item in metric_specs[:3]:
                st.caption(f"metric_spec: {item.get('metric_name') or item.get('source_text')}")
            for item in filter_specs[:3]:
                st.caption(f"filter_spec: {item.get('field')} {item.get('operator')} {item.get('value')}")
            for item in parse_errors[:3]:
                st.caption(f"parse_error: {item.get('spec_kind')}::{item.get('error_code')}")
        else:
            st.caption("No compiled knowledge recorded.")

        st.markdown("#### Rule Checks")
        if sections["rule_checks"]:
            for check in sections["rule_checks"]:
                st.markdown(
                    f"- **Rule**: {check.get('rule', 'unknown')}  \n  Issues: `{check.get('issue_count', 0)}`"
                )
                matched_datasets = check.get("matched_datasets", []) or []
                matched_documents = check.get("matched_documents", []) or []
                if matched_datasets:
                    st.caption(f"datasets: {', '.join(str(item) for item in matched_datasets)}")
                if matched_documents:
                    st.caption(f"documents: {', '.join(str(item) for item in matched_documents)}")
                warnings = check.get("warnings", []) or []
                for warning in warnings[:3]:
                    st.caption(f"warning: {warning}")
        else:
            st.caption("No rule checks recorded.")

        st.markdown("#### Metric Checks")
        if sections["metric_checks"]:
            for check in sections["metric_checks"]:
                st.markdown(
                    f"- **Metric**: {check.get('metric', 'unknown')}  \n"
                    f"  Matched columns: `{len(check.get('matched_columns', []) or [])}`"
                )
                matched_datasets = check.get("matched_datasets", []) or []
                if matched_datasets:
                    st.caption(f"datasets: {', '.join(str(item) for item in matched_datasets)}")
                highlights = check.get("highlights", []) or []
                for highlight in highlights[:3]:
                    st.caption(f"highlight: {highlight}")
        else:
            st.caption("No metric checks recorded.")

        st.markdown("#### Filter Checks")
        if sections["filter_checks"]:
            for check in sections["filter_checks"]:
                st.markdown(f"- **Filter**: {check.get('filter', 'unknown')}")
                matched_datasets = check.get("matched_datasets", []) or []
                matched_documents = check.get("matched_documents", []) or []
                matched_values = check.get("matched_values", []) or []
                if matched_datasets:
                    st.caption(f"datasets: {', '.join(str(item) for item in matched_datasets)}")
                if matched_documents:
                    st.caption(f"documents: {', '.join(str(item) for item in matched_documents)}")
                for value in matched_values[:3]:
                    st.caption(f"value: {value}")
        else:
            st.caption("No filter checks recorded.")

    with info_col2:
        st.markdown("#### Analysis Outputs")
        if sections["outputs"]:
            for raw_output, card in zip(sections["outputs"], build_output_cards(sections["outputs"]), strict=False):
                asset = describe_output_asset(raw_output)
                artifact_ref = find_artifact_reference(task_result, raw_output) if isinstance(task_result, dict) else None
                st.markdown("\n".join([f"**[{card['icon']}] {card['title']}**", f"`{card['type']}`", card["subtitle"]]))
                if asset["path"]:
                    st.code(asset["path"], language=None)
                if asset["exists"] and asset["preview_kind"] == "directory":
                    entries = list_directory_entries(asset["path"])
                    if entries:
                        with st.expander(f"Browse {asset['display_name']}"):
                            for entry in entries:
                                label = "DIR" if entry["is_dir"] else "FILE"
                                st.markdown(f"- **[{label}] {entry['name']}**")
                                st.code(entry["path"], language=None)
                                if not entry["is_dir"] and entry["size"] is not None:
                                    st.caption(f"size={entry['size']} bytes")
                elif artifact_ref and asset["preview_kind"] in {"image", "text"}:
                    fetched = fetch_execution_artifact_bytes(
                        api_base_url,
                        execution_id=artifact_ref["execution_id"],
                        artifact_id=artifact_ref["artifact_id"],
                        tenant_id=tenant_id,
                        workspace_id=workspace_id,
                        api_token=api_token,
                    )
                    if fetched is not None:
                        file_bytes, content_type = fetched
                        if asset["preview_kind"] == "image":
                            st.image(file_bytes, use_container_width=True)
                        else:
                            preview_text = file_bytes.decode("utf-8", errors="ignore")[:1200]
                            if preview_text:
                                st.caption(preview_text)
                        st.download_button(
                            label=f"Download {asset['display_name']}",
                            data=file_bytes,
                            file_name=asset["download_name"],
                            key=f"download-{task_id}-{artifact_ref['artifact_id']}",
                            mime=content_type,
                            use_container_width=True,
                        )
                    else:
                        st.caption("Artifact API unavailable for this output.")
                elif asset["exists"] and asset["preview_kind"] in {"image", "text"}:
                    st.caption("Artifact path present, but no safe artifact handle was found.")
                st.divider()
        else:
            st.caption("No outputs recorded.")

        st.markdown("#### Analysis Caveats")
        if sections["caveats"]:
            for item in sections["caveats"]:
                st.markdown(f"- {item}")
        else:
            st.caption("No caveats recorded.")


def render_technical_details(st: Any, *, sections: dict[str, list[Any]]) -> None:
    st.markdown("#### Executions")
    if sections["executions"]:
        for execution in sections["executions"]:
            st.markdown(
                f"- **{execution.get('execution_id', 'unknown')}**  \n"
                f"  kind=`{execution.get('kind', 'unknown')}` backend=`{execution.get('backend', 'unknown')}` status=`{execution.get('status', 'unknown')}`"
            )
            if execution.get("summary"):
                st.caption(str(execution.get("summary"))[:240])
            if execution.get("artifact_count") is not None:
                st.caption(f"artifacts={execution.get('artifact_count')} tool_calls={execution.get('tool_call_count', 0)}")
    else:
        st.caption("No execution resources recorded.")

    st.markdown("#### Tool Calls")
    if sections["tool_calls"]:
        for tool_call in sections["tool_calls"]:
            st.markdown(
                f"- **{tool_call.get('tool_name', 'unknown')}**  \n"
                f"  phase=`{tool_call.get('phase', 'unknown')}` call_id=`{tool_call.get('tool_call_id', 'unknown')}`"
            )
            if tool_call.get("execution_id"):
                st.caption(f"execution={tool_call.get('execution_id')}")
            if tool_call.get("source_event_type"):
                st.caption(f"source_event={tool_call.get('source_event_type')}")
            if tool_call.get("status"):
                st.caption(f"status={tool_call.get('status')}")
            arguments = tool_call.get("arguments")
            if arguments:
                st.caption(f"args={arguments}")
            result_payload = tool_call.get("result")
            if result_payload:
                st.caption(f"result={result_payload}")
    else:
        st.caption("No tool-call resources recorded.")

    st.markdown("#### Historical Skill Matches")
    if sections["historical_skill_matches"]:
        for match in sections["historical_skill_matches"]:
            st.markdown(f"- **{match.get('name', 'unknown')}**")
            required = match.get("required_capabilities", []) or []
            if required:
                st.caption(f"caps={', '.join(str(item) for item in required)}")
            if match.get("match_source"):
                st.caption(f"source={match.get('match_source')}")
            if match.get("match_reason"):
                st.caption(f"reason={match.get('match_reason')}")
            if match.get("match_score") is not None:
                st.caption(f"score={match.get('match_score')}")
            usage = match.get("usage", {}) or {}
            if usage:
                st.caption(str(usage))
    else:
        st.caption("No historical skill matches recorded.")

    st.markdown("#### Used Historical Skills")
    if sections["used_historical_skills"]:
        for match in sections["used_historical_skills"]:
            st.markdown(f"- **{match.get('name', 'unknown')}** used in code generation")
            stages = match.get("selected_by_stages", []) or []
            if stages:
                st.caption(f"stages={', '.join(str(item) for item in stages)}")
            replay_ids = match.get("used_replay_case_ids", []) or []
            if replay_ids:
                st.caption(f"replay_cases={', '.join(str(item) for item in replay_ids)}")
            capabilities = match.get("used_capabilities", []) or []
            if capabilities:
                st.caption(f"used_caps={', '.join(str(item) for item in capabilities)}")
            usage = match.get("usage", {}) or {}
            if usage:
                st.caption(str(usage))
    else:
        st.caption("No historical skills were used in code generation.")

    st.markdown("#### Parse Diagnostics")
    if sections["parser_reports"]:
        for report in sections["parser_reports"]:
            st.markdown(f"- **{report.get('file_name', 'unknown')}**: mode=`{report.get('parse_mode', 'default')}`")
            diagnostics = report.get("parser_diagnostics", {}) or {}
            if diagnostics:
                st.caption(str(diagnostics))
    else:
        st.caption("No parser diagnostics recorded.")

    st.markdown("#### Task Lease")
    if sections["task_lease"]:
        lease = sections["task_lease"][0]
        st.caption(f"owner={lease.get('owner_id')}")
        st.caption(f"expires_at={lease.get('lease_expires_at')}")
        st.caption(f"backend={lease.get('backend')}")
    else:
        st.caption("No active task lease recorded.")
