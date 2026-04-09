PYTHON_ENV ?= lite_interpreter
API_HOST ?= 127.0.0.1
API_PORT ?= 8000
SIDECAR_HOST ?= 127.0.0.1
SIDECAR_PORT ?= 8765
TASK_ID ?= demo-task-001
HOTSPOT_LINT_PATHS ?= src/dag_engine/nodes/coder_node.py src/dag_engine/nodes/static_codegen.py src/sandbox/docker_executor.py tests/test_docs_consistency.py
FULL_LINT_PATHS ?= src tests scripts config

.PHONY: run-api run-sidecar run-frontend demo-trace create-task test test-docker test-integration test-stream lint fmt-check lint-all fmt-check-all smoke-models

run-api:
	conda run -n $(PYTHON_ENV) python -m uvicorn src.api.main:app --host $(API_HOST) --port $(API_PORT)

run-sidecar:
	conda run -n $(PYTHON_ENV) python scripts/run_deerflow_sidecar.py --host $(SIDECAR_HOST) --port $(SIDECAR_PORT)

run-frontend:
	conda run -n $(PYTHON_ENV) streamlit run src/frontend/app.py

demo-trace:
	conda run -n $(PYTHON_ENV) python scripts/demo_task_trace.py --api-base-url http://$(API_HOST):$(API_PORT) --task-id $(TASK_ID)

create-task:
	conda run -n $(PYTHON_ENV) python scripts/create_task.py --api-base-url http://$(API_HOST):$(API_PORT)

test:
	conda run -n $(PYTHON_ENV) python -m pytest -q

test-docker:
	conda run -n $(PYTHON_ENV) python -m pytest -q tests/test_sandbox.py tests/test_e2e.py::test_static_task_flow_e2e_via_api_with_real_sandbox

test-integration:
	conda run -n $(PYTHON_ENV) python -m pytest -q tests/test_sandbox.py tests/test_e2e.py::test_static_task_flow_e2e_via_api_with_real_sandbox tests/test_deerflow_bridge.py::DeerflowBridgeTests::test_run_uses_sidecar_over_real_local_http_transport

lint:
	conda run -n $(PYTHON_ENV) python -m ruff check $(HOTSPOT_LINT_PATHS)

fmt-check:
	conda run -n $(PYTHON_ENV) python -m ruff format --check $(HOTSPOT_LINT_PATHS)

lint-all:
	conda run -n $(PYTHON_ENV) python -m ruff check $(FULL_LINT_PATHS)

fmt-check-all:
	conda run -n $(PYTHON_ENV) python -m ruff format --check $(FULL_LINT_PATHS)

test-stream:
	conda run -n $(PYTHON_ENV) python -m pytest -q tests/test_api_sse.py tests/test_deerflow_bridge.py tests/test_blackboard.py tests/test_dag_engine.py

smoke-models:
	conda run -n $(PYTHON_ENV) python scripts/smoke_dashscope_litellm.py
