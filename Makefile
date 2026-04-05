PYTHON_ENV ?= lite_interpreter
API_HOST ?= 127.0.0.1
API_PORT ?= 8000
SIDECAR_HOST ?= 127.0.0.1
SIDECAR_PORT ?= 8765
TASK_ID ?= demo-task-001

.PHONY: run-api run-sidecar run-frontend demo-trace create-task test-stream smoke-models

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

test-stream:
	conda run -n $(PYTHON_ENV) python -m pytest -q tests/test_api_sse.py tests/test_deerflow_bridge.py tests/test_blackboard.py tests/test_dag_engine.py

smoke-models:
	conda run -n $(PYTHON_ENV) python scripts/smoke_dashscope_litellm.py
