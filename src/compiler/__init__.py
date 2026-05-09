"""Unified compiler layer — plan compilation + code compilation + knowledge compilation.

plan_compiler: Instructor + response_model=ExecutionStrategy → frozen plan
code_compiler: build_codegen_prompt() consuming ExecutionStrategy constraints → LLM code
kag:           ANTLR business-rule / knowledge-graph / evidence / lexicon compilation
"""

from __future__ import annotations

__all__ = [
    "build_codegen_prompt",
    "compile_plan",
    "CompiledKnowledgeState",
    "CompiledLexicon",
    "EvidenceMaterialPatch",
    "FilterSpec",
    "KnowledgeCompilerService",
    "LexiconCompiler",
    "MetricSpec",
    "RuleSpec",
    "SpecCompiler",
]


def __getattr__(name: str):
    if name == "compile_plan":
        from .plan_compiler import compile_plan

        return compile_plan
    if name == "build_codegen_prompt":
        from .code_compiler import build_codegen_prompt

        return build_codegen_prompt
    # kag compiler — deferred imports to avoid pulling ANTLR unless needed
    if name in {
        "CompiledKnowledgeState",
        "CompiledLexicon",
        "EvidenceMaterialPatch",
        "FilterSpec",
        "KnowledgeCompilerService",
        "LexiconCompiler",
        "MetricSpec",
        "RuleSpec",
        "SpecCompiler",
    }:
        from .kag import (  # type: ignore[assignment]
            CompiledKnowledgeState,
            CompiledLexicon,
            EvidenceMaterialPatch,
            FilterSpec,
            KnowledgeCompilerService,
            LexiconCompiler,
            MetricSpec,
            RuleSpec,
            SpecCompiler,
        )

        return locals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
