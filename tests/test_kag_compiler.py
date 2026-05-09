import json
import uuid

from antlr4 import CommonTokenStream, InputStream
from src.blackboard.execution_blackboard import execution_blackboard
from src.blackboard.schema import ExecutionData
from src.common.contracts import StaticEvidenceBundle, StaticEvidenceRecord
from src.dag_engine.nodes.evidence_compiler_node import evidence_compiler_node
from src.kag.builder.entity_extractor import EntityExtractor
from src.kag.builder.relation_extractor import RelationExtractor
from src.compiler.kag import GraphCompiler, KnowledgeCompilerService, LexiconMatcher, SpecCompiler, SpecParseError
from src.compiler.kag.generated.KnowledgeSpecLexer import KnowledgeSpecLexer
from src.compiler.kag.generated.KnowledgeSpecParser import KnowledgeSpecParser
from src.compiler.kag.types import EvidenceCompilationInput
from src.storage.schema import EntityNode


def test_lexicon_matcher_canonicalizes_aliases_and_categories():
    matcher = LexiconMatcher()
    matches = matcher.match_text("请检查费用报销规则在2024年度是否影响审批流程")
    canonicals = {item.canonical for item in matches}
    categories = {item.category for item in matches}

    assert "报销规则" in canonicals
    assert "审批流程" in canonicals
    assert "影响" in canonicals
    assert {"entity", "causal", "temporal"} <= categories


def test_spec_compiler_builds_structured_specs_from_business_context():
    result = SpecCompiler().compile_business_context(
        rules=["合同必须上传"],
        metrics=["审批时效按合同分组统计"],
        filters=["2024年合同"],
    )

    assert result.rules[0].subject_terms
    assert result.metrics[0].metric_name
    assert result.filters[0].field == "year"
    assert result.errors == []


def test_spec_compiler_extracts_preferred_date_terms_from_metric_text():
    metric = SpecCompiler().parse_metric("按biz_date统计审批时效趋势")
    assert not isinstance(metric, SpecParseError)
    assert "biz_date" in metric.preferred_date_terms


def test_spec_compiler_extracts_filter_temporal_preferences():
    filter_spec = SpecCompiler().parse_filter("按created_at筛选2024年记录")
    assert not isinstance(filter_spec, SpecParseError)
    assert "created_at" in filter_spec.preferred_date_terms or filter_spec.field == "year"


def test_generated_antlr_parser_accepts_rule_spec():
    lexer = KnowledgeSpecLexer(InputStream("RULE subject = 合同 required = 合同"))
    parser = KnowledgeSpecParser(CommonTokenStream(lexer))
    tree = parser.spec()

    assert parser.getNumberOfSyntaxErrors() == 0
    assert tree.ruleSpec() is not None


def test_graph_compiler_rejects_causal_without_explicit_marker():
    entities = [
        EntityNode(id="预算调整", label="semantic", properties={"chunk_id": "c1", "match_id": "m1"}),
        EntityNode(id="采购延期", label="semantic", properties={"chunk_id": "c1", "match_id": "m2"}),
    ]

    result = GraphCompiler.compile_relations(chunk_text_map={"c1": "预算调整 采购延期"}, entities=entities)

    assert any(item["code"] == "missing_causal_marker" for item in result.rejected)


def test_graph_compiler_projects_temporal_specs_into_occurs_at_edges():
    spec_result = SpecCompiler().compile_business_context(
        rules=["合同在2024年度必须上传"],
        metrics=["按biz_date统计审批时效趋势"],
        filters=["按created_at筛选2024年记录"],
    )

    result = GraphCompiler.compile_spec_relations(
        rule_specs=spec_result.rules,
        metric_specs=spec_result.metrics,
        filter_specs=spec_result.filters,
    )

    triples = [item.triple for item in result.accepted]
    assert triples
    assert all(triple.relation == "OCCURS_AT" for triple in triples)
    assert any(triple.tail == "biz_date" for triple in triples)
    assert any(triple.tail == "created_at" for triple in triples)
    assert any(triple.tail == "2024" for triple in triples)
    assert all(triple.tail_label == "temporal" for triple in triples)
    assert any((triple.properties.get("provenance") or {}).get("template_id") == "metric.temporal.preference.occurs_at" for triple in triples)


def test_relation_extractor_emits_validated_triples_with_provenance():
    extractor = EntityExtractor(use_llm=False)
    text = "预算调整因为合同规则变化导致采购延期，发生在2024年。"
    entities = extractor.extract_entities(text, doc_id="doc-1", chunk_id="chunk-1")
    triples = RelationExtractor.extract_relations({"chunk-1": text}, entities)

    assert triples
    assert any(triple.relation == "CAUSES" for triple in triples)
    assert all((triple.properties.get("provenance") or {}).get("template_id") for triple in triples)


def test_external_evidence_compiler_keeps_text_only_records_as_hits(tmp_path, monkeypatch):
    monkeypatch.setattr("src.compiler.kag.evidence.OUTPUT_DIR", str(tmp_path))

    patch = KnowledgeCompilerService.compile_external_evidence(
        EvidenceCompilationInput(
            source="static_evidence",
            query="查公开事实",
            tenant_id="tenant_hits",
            workspace_id="ws_hits",
            task_id="task_hits",
            records=[
                StaticEvidenceRecord(
                    title="公开报告",
                    url="https://example.com/report",
                    snippet="这是一段只有描述没有可计算事实的资料。",
                    source_type="search_result",
                )
            ],
        )
    )

    assert patch.structured_datasets == []
    assert patch.material_refresh_actions == ["context_builder"]
    assert patch.knowledge_hits
    assert patch.knowledge_hits[0]["type"] == "search_result"
    assert patch.knowledge_hits[0]["metadata"]["source_sha256"]
    assert "https://example.com/report" in patch.evidence_refs


def test_external_evidence_compiler_materializes_complete_fact_rows(tmp_path, monkeypatch):
    monkeypatch.setattr("src.compiler.kag.evidence.OUTPUT_DIR", str(tmp_path))

    patch = KnowledgeCompilerService.compile_external_evidence(
        EvidenceCompilationInput(
            source="static_evidence",
            query="编译公开结构化事实",
            tenant_id="tenant_dataset",
            workspace_id="ws_dataset",
            task_id="task_dataset",
            records=[
                StaticEvidenceRecord(
                    title="季度披露",
                    url="https://example.com/q1",
                    text="""
                    ```json
                    [{"entity":"ACME","metric":"revenue","period":"2024Q1","value":123.5,"currency":"CNY","source":"公开季报","source_quote":"Q1 revenue 123.5"}]
                    ```
                    """,
                    source_type="fetched_document",
                )
            ],
        )
    )

    assert patch.material_refresh_actions == ["data_inspector"]
    assert len(patch.structured_datasets) == 1
    dataset = patch.structured_datasets[0]
    payload = json.loads(
        tmp_path.joinpath(
            "tenant_dataset",
            "ws_dataset",
            "evidence-materials-task_dataset",
            dataset.file_name,
        ).read_text(encoding="utf-8")
    )
    row = payload["items"][0]

    assert dataset.file_sha256
    assert dataset.load_kwargs == {"format": "json"}
    assert row["entity"] == "ACME"
    assert row["metric"] == "revenue"
    assert row["currency"] == "CNY"
    assert row["source"] == "公开季报"
    assert row["source_sha256"]
    assert row["source_quote"] == "Q1 revenue 123.5"


def test_external_evidence_compiler_extracts_business_context_delta(tmp_path, monkeypatch):
    monkeypatch.setattr("src.compiler.kag.evidence.OUTPUT_DIR", str(tmp_path))

    patch = KnowledgeCompilerService.compile_external_evidence(
        EvidenceCompilationInput(
            source="dynamic_resume",
            query="整理规则和指标",
            tenant_id="tenant_context",
            workspace_id="ws_context",
            task_id="task_context",
            findings=["RULE: 合同必须上传\nMETRIC: 按合同统计审批时效\nFILTER: 仅看2024年"],
            artifact_refs=["deerflow:thread-1"],
        )
    )

    assert patch.structured_datasets == []
    assert patch.business_context_delta.rules == ["合同必须上传"]
    assert patch.business_context_delta.metrics == ["按合同统计审批时效"]
    assert patch.business_context_delta.filters == ["仅看2024年"]
    assert patch.business_context_delta.sources == [patch.evidence_refs[-1]]


def test_evidence_compiler_node_persists_static_dataset_patch(tmp_path, monkeypatch):
    monkeypatch.setattr("src.compiler.kag.evidence.OUTPUT_DIR", str(tmp_path))

    tenant_id = "tenant_node_static"
    task_id = f"task_node_static_{uuid.uuid4().hex}"
    workspace_id = "ws_node_static"
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id=workspace_id,
            static={
                "static_evidence_bundle": StaticEvidenceBundle(
                    records=[
                        StaticEvidenceRecord(
                            title="季度披露",
                            url="https://example.com/static",
                            text='[{"entity":"ACME","metric":"revenue","period":"2024Q1","value":88,"currency":"USD","source":"公开披露"}]',
                            source_type="fetched_document",
                        )
                    ]
                )
            },
        ),
    )

    result = evidence_compiler_node(
        {
            "tenant_id": tenant_id,
            "task_id": task_id,
            "workspace_id": workspace_id,
            "input_query": "把公开披露转成可计算材料",
            "evidence_compiler_source": "static_evidence",
        }
    )
    updated = execution_blackboard.read(tenant_id, task_id)

    assert result["material_refresh_actions"] == ["data_inspector"]
    assert updated is not None
    assert len(updated.inputs.structured_datasets) == 1
    assert updated.inputs.structured_datasets[0].file_sha256
    assert updated.knowledge.knowledge_snapshot.evidence_refs == ["https://example.com/static"]


def test_evidence_compiler_node_uses_dynamic_resume_findings_for_hits(tmp_path, monkeypatch):
    monkeypatch.setattr("src.compiler.kag.evidence.OUTPUT_DIR", str(tmp_path))

    tenant_id = "tenant_node_dynamic"
    task_id = f"task_node_dynamic_{uuid.uuid4().hex}"
    workspace_id = "ws_node_dynamic"
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(tenant_id=tenant_id, task_id=task_id, workspace_id=workspace_id),
    )

    result = evidence_compiler_node(
        {
            "tenant_id": tenant_id,
            "task_id": task_id,
            "workspace_id": workspace_id,
            "input_query": "整理外部研究结论",
            "evidence_compiler_source": "dynamic_resume",
            "dynamic_research_findings": ["这是文本研究发现，没有结构化字段。"],
            "dynamic_artifacts": ["/tmp/report.md"],
        }
    )
    updated = execution_blackboard.read(tenant_id, task_id)

    assert result["material_refresh_actions"] == ["context_builder"]
    assert updated is not None
    assert updated.inputs.structured_datasets == []
    assert updated.knowledge.knowledge_snapshot.hits[0]["type"] == "dynamic_finding"
    assert "/tmp/report.md" in updated.knowledge.knowledge_snapshot.evidence_refs
