from antlr4 import CommonTokenStream, InputStream
from src.kag.builder.entity_extractor import EntityExtractor
from src.kag.builder.relation_extractor import RelationExtractor
from src.kag.compiler import GraphCompiler, LexiconMatcher, SpecCompiler, SpecParseError
from src.kag.compiler.generated.KnowledgeSpecLexer import KnowledgeSpecLexer
from src.kag.compiler.generated.KnowledgeSpecParser import KnowledgeSpecParser
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
