# lite-interpreter

`lite-interpreter` is a production-oriented data-intelligence agent platform prototype.

Its current architecture is:

- macro orchestration: deterministic DAG
- micro orchestration: DeerFlow as a dynamic `Super Node`
- governance plane: local harness policy + risk decisions inspired by AutoHarness
- control plane: Blackboard + Event Bus + MCP-style state sync
- execution boundary: final code execution remains inside `lite-interpreter` sandbox
- model backend: DashScope models through LiteLLM
- KAG framework adapter: LlamaIndex

The project goal is not to build a free-form autonomous agent first. The goal is to build a controllable, observable, secure agent runtime for enterprise-style data analysis tasks.

Recent design emphasis:

- keep the system explicitly centered on data-analysis tasks
- classify tasks into dataset / rule / hybrid / dynamic-research analysis modes
- keep context compression evidence-aware instead of treating history as generic chat text
- ship deterministic evals that verify routing and evidence preservation

## 1. Core design

Current high-level design:

- deterministic DAG handles stable SOP-like paths
- DeerFlow dynamic swarm handles complex long-tail exploration
- Blackboard is the source of truth for task state and execution state
- dynamic traces are written back to Blackboard and streamed to UI
- successful dynamic paths can be harvested into reusable skill candidates

Key principles:

- keep main control in `lite-interpreter`
- use DeerFlow as a high-capability tool, not as the system owner
- keep code execution under local audit + sandbox
- route dynamic and sandbox actions through a shared governance layer
- prefer explicit state, bounded budgets, and reversible flows

## 2. Model and KAG choices

### Model provider

All primary model calls are now designed around:

- DashScope
- LiteLLM

Configured aliases:

- `fast_model`
- `reasoning_model`
- `coder_model`
- `embedding_model`

Config file:

- `litellm_config.yml`
- `config/analysis_runtime.yaml`

Environment variable:

- `DASHSCOPE_API_KEY`

### KAG framework choice

The project keeps the original KAG design philosophy and uses:

- Docling for parsing
- LlamaIndex as the framework adapter layer
- Postgres as source-of-truth text storage
- Qdrant for vector recall
- Neo4j for graph recall

Important:

- KAG was not rewritten into DeerFlow
- KAG was not collapsed into generic LangChain chains
- The original design ideas remain:
  - layout-aware chunking
  - parent-child chunking
  - sentence-splitter fallback
  - MAGMA-style graph extraction
  - hybrid recall with rerank and budget control

## 3. What is already implemented

### Environment and runtime

- new Python 3.12 conda env: `lite_interpreter`
- DeerFlow installed in that env from local source
- CPU-only PyTorch installed for compatibility
- Streamlit installed for UI demo

### Dynamic orchestration

- `config/analysis_runtime.yaml`
  - defines lightweight data-analysis runtime policy for routing, compression, and summary purposes
- `src/dynamic_engine/deerflow_bridge.py`
  - supports `embedded`
  - supports `sidecar`
  - supports `auto`
- `src/dynamic_engine/supervisor.py`
  - prepares `TaskEnvelope`, `ExecutionIntent`, governance decision, and dynamic request
- `src/dynamic_engine/runtime_gateway.py`
  - isolates runtime execution from DAG-owned planning
- `src/dynamic_engine/runtime_registry.py`
  - selects the concrete dynamic runtime backend behind the gateway
- `src/dynamic_engine/trace_normalizer.py`
  - normalizes runtime events before state sync and SSE projection
- `src/dag_engine/nodes/dynamic_swarm_node.py`
  - coordinates supervisor + gateway + trace normalization
  - writes request to Blackboard
  - forwards trace events
  - writes result back into execution state
- `src/dynamic_engine/runtime_backends.py`
  - exposes runtime capability manifest metadata for the active backend
- `src/api/routers/runtime_router.py`
  - exposes runtime inventory and capability inspection endpoints

### Harness governance

- `config/harness_policy.yaml`
  - governance mode, profiles, risk thresholds, sandbox deny patterns
- `src/harness/governor.py`
  - emits allow/deny decisions for dynamic delegation and sandbox execution
  - now resolves allowed/requested abilities through the capability registry
- `src/common/capability_registry.py`
  - canonical registry for `knowledge_query`, `sandbox_exec`, `state_sync`, `dynamic_trace`, and related aliases
- `src/blackboard/schema.py`
  - stores governance mode/profile/decision history per task

### Sandbox execution plane

- `src/sandbox/session_manager.py`
  - creates lightweight `SandboxSession` handles around each sandbox execution
- `src/sandbox/docker_executor.py`
  - records session lifecycle alongside the existing Docker execution flow
- `src/mcp_gateway/tools/sandbox_exec_tool.py`
  - normalizes sandbox results into `ExecutionRecord` while preserving session metadata

### SkillNet and capability governance

- `src/skillnet/skill_schema.py`
  - skill descriptors now carry `required_capabilities`, replay cases, and validation state
- `src/skillnet/skill_harvester.py`
  - harvested dynamic skills now derive required capabilities from governance/runtime context
  - generates replay cases and validator-backed metadata for each candidate
- `src/skillnet/skill_validator.py`
  - runs lightweight validation before a candidate can be treated as promotion-ready
- `src/skillnet/skill_retriever.py`
  - filters skill candidates by available capabilities and approved promotion state
- `src/skillnet/skill_promoter.py`
  - derives promotion state (`harvested` / `approved` / `needs_review` / `rejected`) from validation + authorization
- `src/mcp_gateway/tools/skill_auth_tool.py`
  - authorizes a skill against a governance profile using capability metadata
- `src/dag_engine/nodes/analyst_node.py` / `src/dag_engine/nodes/coder_node.py`
  - approved skills now appear in planning and code-generation payloads, so promoted skills start affecting execution paths
  - promotion provenance and skill strategy hints are now carried into execution planning
- `src/storage/repository/memory_repo.py`
  - persists approved skills per tenant/workspace so later tasks can reuse historical promoted skills
  - now supports capability-filtered lookup for router / analyst / coder reuse
  - records lightweight usage telemetry for matched historical skills
- `src/skillnet/skill_retriever.py`
  - now derives match source/reason/score for historical approved skill selection
- `historical_skill_matches` / `used_historical_skills`
  - task state and final response now distinguish matched historical skills from those actually used in code generation
  - codegen-used historical skills now record replay-case ids and capability ids for richer feedback
- `MemoryRepo.record_skill_outcome(...)`
  - task completion now feeds success/failure counters back into historical skill usage telemetry

### Blackboard and event flow

- `src/blackboard/schema.py`
  - dynamic request / summary / trace / artifacts / skill candidate fields
  - governance mode / profile / decision fields
  - normalized control-plane fields: `task_envelope`, `execution_intent`, `decision_log`, `execution_record`
- `src/common/contracts.py`
  - now also defines `RuntimeCapabilityManifest`, `ExecutionEvent`, and `ToolCallRecord`
- `src/mcp_gateway/tools/state_sync_tool.py`
  - partial patch sync
  - append trace event helper
- `src/common/event_bus.py`
  - subscribe / unsubscribe support
  - mirrors task events into an append-only event journal for replay
- `src/common/event_journal.py`
  - task-scoped event replay store used by SSE
- `src/common/schema.py`
  - `UI_TASK_TRACE_UPDATE`
  - `UI_TASK_GOVERNANCE_UPDATE`

### API and streaming

- `src/api/main.py`
- `src/api/routers/sse_router.py`
- `src/api/routers/analysis_router.py`
- `src/api/routers/execution_router.py`
- `src/api/routers/diagnostics_router.py`
- `src/api/routers/runtime_router.py`
- `src/api/schemas.py`

Available routes:

- `GET /health`
- `GET /api/diagnostics`
- `GET /api/conformance`
- `GET /api/runtimes`
- `GET /api/runtimes/{runtime_id}/capabilities`
- `GET /api/audit/logs`
- `POST /api/session/login`
- `GET /api/session/me`
- `POST /api/tasks`
- `GET /api/tasks/{task_id}/executions`
- `GET /api/tasks/{task_id}/result`
- `GET /api/tasks/{task_id}/events`
- `POST /api/dev/tasks/{task_id}/demo-trace`
- `POST /api/uploads`
- `GET /api/knowledge/assets`
- `GET /api/skills`
- `GET /api/executions/{execution_id}`
- `GET /api/executions/{execution_id}/artifacts`
- `GET /api/executions/{execution_id}/tool-calls`
- `GET /api/executions/{execution_id}/events`

Operational notes:

- task / execution / knowledge / memory / upload / asset / skill APIs now require `tenant_id` + `workspace_id` scope, either from authenticated API token binding or explicit query/form scope
- set `API_AUTH_TOKENS_JSON` to enable bearer-token auth; when configured, the token scope is authoritative over client-supplied tenant/workspace values
- token roles are hierarchical: `viewer` for read-only task/runtime access, `operator` for task creation and uploads, `admin` for policy, diagnostics, and demo-trace controls
- the API now also supports local user-to-session login via `POST /api/session/login`; session tokens carry one or more tenant/workspace grants and reuse the same role model
- `GET /api/audit/logs` is `admin`-only and returns persistent API audit records scoped to the caller's tenant/workspace
- `GET/POST /api/policy`, `POST /api/dev/tasks/{task_id}/demo-trace`, and `GET /api/diagnostics` are disabled by default and must be explicitly enabled via env vars
- set `STRICT_PERSISTENCE=true` to disable silent in-memory fallback for state/memory repositories
- `/api/diagnostics` now exposes repository status, startup recovery, and detected Postgres driver state when enabled
- Postgres-backed persistence now expects a SQLAlchemy-compatible driver such as `psycopg` or `psycopg2`; the default dependency set includes `psycopg[binary]`

### Frontend demo

- `src/frontend/app.py`
- `src/frontend/pages/task_console.py`
- `src/frontend/pages/knowledge_manager.py`
- `src/frontend/pages/skill_manager.py`
- `src/frontend/components/file_uploader.py`
- `src/frontend/components/status_stream.py`

Capabilities:

- connect to SSE via browser `EventSource`
- view task status updates
- view dynamic trace updates
- view harness governance allow/deny decisions
- fetch task result, executions, and tool-call resources through API
- attach execution-level streams after executions are discovered
- distinguish static-chain synthetic tool calls from dynamic runtime tool calls in the Task Console
- upload workspace assets directly from the Task Console
- inspect uploaded knowledge assets and parser/index state
- inspect approved and preset reusable skills
- create a minimal real task
- trigger a fake demo trace
- optionally authenticate requests from the Task Console with an API token

### Model client and KAG framework adapter

- `src/common/llm_client.py`
  - unified LiteLLM wrapper
  - sync + async wrappers for chat / embeddings
- `src/kag/retriever/query_engine.py`
  - emits evidence-aware retrieval payloads and normalized hit lists
  - now also emits `EvidencePacket` for normalized knowledge-plane results
- `src/mcp_gateway/tools/knowledge_query_tool.py`
  - returns evidence-aware retrieval payloads instead of a thin hit wrapper
- `src/kag/framework/llama_index_adapter.py`
  - LlamaIndex sentence splitter
  - LiteLLM + DashScope embedding adapter
- `src/kag/builder/embedding.py`
  - main embedding path uses DashScope via LiteLLM
- `src/kag/builder/chunker.py`
  - sentence fallback uses LlamaIndex splitter
- `src/kag/builder/parser.py`
  - returns typed `ParsedDocument`
  - rebuilds section hierarchy from Docling text items instead of assuming `document.sections`
- `src/kag/retriever/recall/hybrid_search.py`
  - query embedding uses the new embedding path
- `src/dag_engine/nodes/data_inspector.py`
  - fast LLM fallback now uses `fast_model`

### Token budgeting

- `src/common/utils.py`
  - `estimate_tokens_fast` for classification / rough heuristics
  - `count_text_tokens_exact` and `count_message_tokens_exact` for prompt-window enforcement
  - `fit_items_to_budget` for final prompt assembly
- `src/kag/retriever/budget.py`
  - now enforces exact-fit budget against the target context model
- `src/dag_engine/nodes/context_builder_node.py`
  - performs final context fit before handing material to downstream nodes
  - now emits an `analysis_brief` with evidence refs, known gaps, and next-step guidance for data-analysis planning

### Data-analysis runtime and evals

- `src/runtime/analysis_runtime.py`
  - classifies tasks into `dataset_analysis`, `document_rule_analysis`, `hybrid_analysis`, `dynamic_research_analysis`, and `need_more_inputs`
  - resolves lightweight runtime decisions per call purpose without turning the project into a generic framework
- `src/evals/runner.py`
  - runs deterministic seed evals for route correctness and evidence pinning
- `src/evals/cases.py`
  - stores seed data-analysis cases for dataset, rule, hybrid, and dynamic-research tasks

### Demo and utility scripts

- `scripts/run_deerflow_sidecar.py`
- `scripts/smoke_deerflow_bridge.py`
- `scripts/smoke_dashscope_litellm.py`
- `scripts/demo_task_trace.py`
- `scripts/create_task.py`
- `scripts/check_hybrid_readiness.py`

### Verification

Use the `lite_interpreter` conda env:

```bash
conda run -n lite_interpreter python -m pytest -q
```

Deterministic eval report:

```bash
conda run -n lite_interpreter python -m src.evals.run
```

Write reports into a specific project directory when needed:

```bash
conda run -n lite_interpreter python -m src.evals.run --output-dir artifacts/evals
```

The latest verified test baseline lives in `docs/project_status.md`.

## 4. Current status

The project status source of truth is `docs/project_status.md`. In short:

- the core execution loop is real and regression-tested
- the repository is strongest today as a controlled runtime prototype, not a finished product platform
- core/support/experimental boundaries are tracked explicitly instead of being inferred from ad-hoc prose

## 5. Current maturity tiers

### Core

- deterministic DAG + DeerFlow dynamic super node
- blackboard / event bus / event journal control plane
- harness governance + local sandbox execution boundary
- API / SSE main path
- Task Console

### Support

- KAG retrieval and context assembly
- SkillNet harvesting, validation, promotion, and historical reuse
- execution / artifacts / tool-calls / diagnostics / conformance resources
- deterministic evals and analysis-runtime task classification

### Experimental

- `src/frontend/pages/knowledge_manager.py`
- `src/frontend/pages/skill_manager.py`
- heavier product-style management surfaces outside the main runtime loop
- long-horizon expansion areas that do not change whether the current runtime is valid

## 6. Recommended environment

Use:

```bash
conda run -n lite_interpreter <command>
```

Why this env:

- Python 3.12 compatible with DeerFlow harness
- DeerFlow already installed
- Streamlit already installed
- tests already validated there
- project commands in `Makefile` already default to this env

If you prefer an interactive shell first:

```bash
conda activate lite_interpreter
```

## 7. Important environment variables

### DashScope / LiteLLM

- `DASHSCOPE_API_KEY`

### DeerFlow runtime

- `DEERFLOW_RUNTIME_MODE`
- `DEERFLOW_SIDECAR_URL`
- `DEERFLOW_SIDECAR_TIMEOUT`
- `DEERFLOW_CONFIG_PATH`
- `DEERFLOW_MODEL_NAME`
- `DEERFLOW_MAX_EVENTS`
- `DEERFLOW_MAX_STEPS`
- `DEERFLOW_RECURSION_LIMIT`

## 8. Main commands

From repo root:

```bash
make run-sidecar
make run-api
make run-frontend
make demo-trace
make create-task
make test
make test-docker
make test-integration
make lint
make fmt-check
make lint-all
make fmt-check-all
make test-stream
make smoke-models
```

## 9. Fastest demo path

### Start sidecar

```bash
export OPENAI_API_KEY=your_real_key
export DEERFLOW_CONFIG_PATH=/home/linsir365/projects/deer-flow/config.yaml
make run-sidecar
```

### Start API

```bash
export DEERFLOW_RUNTIME_MODE=sidecar
export DEERFLOW_SIDECAR_URL=http://127.0.0.1:8765
export DEERFLOW_CONFIG_PATH=/home/linsir365/projects/deer-flow/config.yaml
make run-api
```

### Start frontend

```bash
make run-frontend
```

### Trigger a fake trace

```bash
make demo-trace
```

### Trigger a minimal real task

```bash
make create-task
```

## 10. Best files to read first

If you want to understand the project quickly:

1. `docs/code_tour.md`
2. `docs/project_status.md`
3. `docs/deerflow_integration.md`
4. `docs/runtime_support_matrix.md`
5. `docs/openharness_adaptation_plan.md`
6. `config/settings.py`
7. `litellm_config.yml`
8. `src/common/llm_client.py`
9. `src/kag/framework/llama_index_adapter.py`
10. `src/dynamic_engine/deerflow_bridge.py`
11. `src/dag_engine/nodes/dynamic_swarm_node.py`
12. `src/api/routers/sse_router.py`
13. `src/frontend/pages/task_console.py`

## 11. Current known limitations

- DeerFlow live task execution still depends on valid external model credentials
- the frontend is a demo-grade console, not a polished product UI
- not all DAG business nodes are complete
- dependency surface is broad because DeerFlow and KAG both bring heavy stacks
- experimental surfaces remain intentionally de-emphasized relative to the runtime core
- `make test-docker` is the quickest way to verify the real Docker-backed sandbox path when this session can reach the local Docker daemon
- `make test-integration` verifies the strongest local integration slice: real Docker sandbox plus the DeerFlow sidecar transport bridge
- `make lint` / `make fmt-check` currently enforce the touched hotspot files; use `make lint-all` / `make fmt-check-all` to inspect the broader repo-wide debt

## 12. Supporting docs

- `docs/deerflow_integration.md`
- `docs/code_tour.md`
- `directory.txt`
- `项目二.md`
