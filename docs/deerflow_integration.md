# DeerFlow Integration Guide

## Goal

`lite-interpreter` uses DeerFlow as the dynamic research / sub-agent engine
behind `dynamic_swarm_node`, while keeping final code execution inside
`lite-interpreter`'s own sandbox.

That means the boundary is:

- DeerFlow: dynamic planning, tool-mediated research, sub-agent orchestration
- lite-interpreter sandbox: final Python execution, audit, artifact control

## Official DeerFlow capabilities we rely on

DeerFlow's official materials show two integration surfaces that matter here:

1. Embedded Python client:
   - `from deerflow.client import DeerFlowClient`
   - `client = DeerFlowClient()`
   - `client.chat(...)`
2. Docker / Compose deployment for running the full DeerFlow service stack

For `lite-interpreter`, the current bridge is designed around the embedded
Python client first, because it fits the "DAG super-node" architecture best.

## Recommended integration modes

### Mode A: Embedded Python client

Best for the current `lite-interpreter` architecture.

How it works:

- Install the DeerFlow harness package into the same Python environment as
  `lite-interpreter`
- Let `src/dynamic_engine/deerflow_bridge.py` import `deerflow.client`
- Use `DeerFlowClient` directly from the `dynamic_swarm_node`

Pros:

- Lowest orchestration overhead
- Best fit for "Dynamic Swarm Super Node"
- No extra service discovery layer

Tradeoffs:

- Heavier local Python environment
- DeerFlow dependency stack and config must be present in the runtime env

### Mode B: Docker / service deployment

Best for stronger isolation and more production-like deployment.

How it works:

- Run DeerFlow with its official Docker / Compose path
- `lite-interpreter` talks to DeerFlow through a future service adapter

Pros:

- Better isolation
- Cleaner separation of runtime dependencies

Tradeoffs:

- More moving parts
- Requires health checks, timeouts, service config, and request adaptation

### Mode C: Sidecar adapter

Best long-term production pattern if DeerFlow becomes a permanent subsystem.

How it works:

- A dedicated local adapter process owns `DeerFlowClient`
- `lite-interpreter` calls that adapter instead of importing DeerFlow directly

Pros:

- Keeps the main app boundary clean
- Easier to evolve from embedded mode to service mode

Tradeoffs:

- More engineering work than Mode A
- Requires one extra local process and a small HTTP contract

## What `lite-interpreter` currently expects

The bridge does **not** assume DeerFlow is vendored in this repo.

Current assumptions:

- The runtime can optionally import `deerflow.client`
- `DEERFLOW_CONFIG_PATH` may point at a DeerFlow `config.yaml`
- `DEERFLOW_MODEL_NAME` may optionally override the default DeerFlow model

If DeerFlow is not installed or importable:

- the bridge degrades to `dynamic_status=unavailable`
- the DAG keeps a structured preview instead of crashing

## Practical installation options

Because DeerFlow's official repo contains a buildable harness package under
`backend/packages/harness/pyproject.toml`, practical installation usually means
installing that package from source rather than assuming a public PyPI package.

Common approaches:

### Option 1: Install from a local DeerFlow checkout

```bash
git clone https://github.com/bytedance/deer-flow.git
cd deer-flow/backend/packages/harness
pip install .
```

Or with `uv`:

```bash
git clone https://github.com/bytedance/deer-flow.git
cd deer-flow/backend/packages/harness
uv pip install .
```

Important:

- DeerFlow harness metadata currently declares `requires-python >= 3.12`
- your current `lite-interpreter` conda environment is `Python 3.10.9`
- so embedded-mode installation will fail in the current env unless you upgrade
  that env to Python 3.12+ or choose a service/sidecar deployment mode

### Option 2: Install from the official GitHub repo subdirectory

If your tooling supports VCS subdirectory installs, a practical pattern is:

```bash
pip install "git+https://github.com/bytedance/deer-flow.git#subdirectory=backend/packages/harness"
```

Or with `uv`:

```bash
uv pip install "git+https://github.com/bytedance/deer-flow.git#subdirectory=backend/packages/harness"
```

Note:

- This command shape is a Python packaging convention inferred from the DeerFlow
  repo layout and packaging metadata.
- You should still treat DeerFlow's official repo and README as the source of
  truth.

## Recommended setup for this repository

For this repository, the most practical current setup is:

- keep `lite-interpreter` as the main application
- run DeerFlow in a dedicated Python 3.12 environment
- expose DeerFlow through a small localhost sidecar service
- let `lite-interpreter` call that sidecar over HTTP

Internally, DeerFlow is now selected through the dynamic runtime registry:

- `DynamicSupervisor` prepares the bounded dynamic run
- `RuntimeGateway` resolves the configured backend from `runtime_registry`
- the default backend is still `deerflow`

That means DeerFlow remains the default runtime, but it is no longer hard-wired
into the DAG node itself.

This is now supported directly by:

- `scripts/run_deerflow_sidecar.py`
- `DEERFLOW_RUNTIME_MODE=sidecar`
- `DEERFLOW_SIDECAR_URL=http://127.0.0.1:8765`

### Sidecar startup example

```bash
export OPENAI_API_KEY=your_real_key
export DEERFLOW_CONFIG_PATH=/home/linsir365/projects/deer-flow/config.yaml
conda run -n lite_interpreter python scripts/run_deerflow_sidecar.py --host 127.0.0.1 --port 8765
```

### Main app sidecar configuration

```bash
export DEERFLOW_RUNTIME_MODE=sidecar
export DEERFLOW_SIDECAR_URL=http://127.0.0.1:8765
```

In `auto` mode, the bridge prefers sidecar when `DEERFLOW_SIDECAR_URL` is set,
and falls back to embedded mode otherwise.

## Demo workflow

Once both the API and sidecar are running, you can demo the full streaming path
without waiting for a real business task:

1. Start the sidecar:

```bash
export OPENAI_API_KEY=your_real_key
export DEERFLOW_CONFIG_PATH=/home/linsir365/projects/deer-flow/config.yaml
conda run -n lite_interpreter python scripts/run_deerflow_sidecar.py --host 127.0.0.1 --port 8765
```

2. Start the API:

```bash
export DEERFLOW_RUNTIME_MODE=sidecar
export DEERFLOW_SIDECAR_URL=http://127.0.0.1:8765
export DEERFLOW_CONFIG_PATH=/home/linsir365/projects/deer-flow/config.yaml
conda run -n lite_interpreter python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000
```

3. Start the Task Console:

```bash
conda run -n lite_interpreter streamlit run src/frontend/app.py
```

4. Trigger a fake task trace:

```bash
conda run -n lite_interpreter python scripts/demo_task_trace.py --api-base-url http://127.0.0.1:8000 --task-id demo-task-001
```

5. In the Task Console, open task `demo-task-001`

This shows:

- task created event
- task status updates
- dynamic trace update events
- task finished event

### Real task creation demo

You can also create a minimal real task through the API:

```bash
cd /home/linsir365/projects/lite-interpreter
conda run -n lite_interpreter python scripts/create_task.py --api-base-url http://127.0.0.1:8000
```

The API will:

- create a real task id
- initialize `ExecutionBlackboard`
- run the minimal routing flow in the background
- emit status / trace events that the Task Console can display

### Makefile shortcuts

From `/home/linsir365/projects/lite-interpreter`:

```bash
make run-sidecar
make run-api
make run-frontend
make demo-trace
make create-task
make test-stream
```

## Configuration for `lite-interpreter`

Environment variables used by the bridge:

- `DEERFLOW_CLIENT_MODULE` — defaults to `deerflow.client`
- `DEERFLOW_RUNTIME_MODE` — `auto` / `embedded` / `sidecar`
- `DEERFLOW_SIDECAR_URL` — sidecar base URL, e.g. `http://127.0.0.1:8765`
- `DEERFLOW_SIDECAR_TIMEOUT` — HTTP timeout for sidecar requests
- `DEERFLOW_CONFIG_PATH` — optional path to DeerFlow `config.yaml`
- `DEERFLOW_MODEL_NAME` — optional model override
- `DEERFLOW_MAX_EVENTS` — maximum events captured from DeerFlow stream
- `DEERFLOW_MAX_STEPS` — dynamic step budget injected into DeerFlow context
- `DEERFLOW_RECURSION_LIMIT` — recursion limit forwarded to DeerFlow

Example:

```bash
export DEERFLOW_RUNTIME_MODE=sidecar
export DEERFLOW_SIDECAR_URL=http://127.0.0.1:8765
export DEERFLOW_CONFIG_PATH=/path/to/deer-flow/config.yaml
export DEERFLOW_MODEL_NAME=
export DEERFLOW_MAX_EVENTS=64
```

## Smoke test

Use:

```bash
python3 scripts/smoke_deerflow_bridge.py
```

Optional live chat:

```bash
python3 scripts/smoke_deerflow_bridge.py --run-chat --message "Analyze this paper for me"
```

## Security boundary

This project intentionally keeps the boundary strict:

- DeerFlow may perform dynamic research through its own tool layer
- DeerFlow output is treated as planning / orchestration output
- Generated Python must still go through `lite-interpreter`'s audit and sandbox
- `lite-interpreter` does not delegate host-level code execution to DeerFlow

## Current project constraint

During validation on this machine, installing DeerFlow into the
`lite-interpreter` conda env failed because DeerFlow's harness package requires
Python 3.12+, while the current env is Python 3.10.9.

That means:

- the bridge code is ready for embedded integration
- live embedded execution in the current env is blocked by Python version
- the practical next choices are:
  1. upgrade `lite-interpreter` env to Python 3.12+
  2. run DeerFlow out-of-process via Docker/service mode
  3. create a dedicated 3.12 DeerFlow sidecar env and keep `lite-interpreter`
     on 3.10

## Source references

- DeerFlow README embedded client section:
  `https://github.com/bytedance/deer-flow/blob/main/README.md`
- DeerFlow harness packaging metadata:
  `https://github.com/bytedance/deer-flow/blob/main/backend/packages/harness/pyproject.toml`
