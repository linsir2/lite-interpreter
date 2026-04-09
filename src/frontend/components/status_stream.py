"""HTML-based task status stream component for Streamlit or notebook-style embedding."""

from __future__ import annotations

import html
from urllib.parse import urlencode


def build_status_stream_html(
    *,
    api_base_url: str,
    task_id: str = "",
    execution_id: str = "",
    tenant_id: str = "",
    workspace_id: str = "",
    api_token: str = "",
    height: int = 420,
) -> str:
    query = {}
    if tenant_id:
        query["tenant_id"] = tenant_id
    if workspace_id:
        query["workspace_id"] = workspace_id
    if api_token:
        query["access_token"] = api_token
    query_string = urlencode(query)
    if execution_id:
        stream_url = f"{api_base_url.rstrip('/')}/api/executions/{execution_id}/events"
        title = "Execution Stream"
        state_label = "Execution State"
    else:
        stream_url = f"{api_base_url.rstrip('/')}/api/tasks/{task_id}/events"
        title = "Dynamic Task Stream"
        state_label = "Task State"
    if query_string:
        stream_url = f"{stream_url}?{query_string}"

    safe_stream_url = html.escape(stream_url, quote=True)
    return f"""
<div style="font-family: ui-monospace, SFMono-Regular, Menlo, monospace; border: 1px solid #d9d9d9; border-radius: 12px; overflow: hidden; background: #fcfcfc;">
  <div style="padding: 12px 16px; background: #111827; color: #f9fafb;">
    <div style="font-size: 14px; font-weight: 700;">{title}</div>
    <div style="font-size: 12px; opacity: 0.8;">{html.escape(stream_url)}</div>
  </div>
  <div style="display:grid; grid-template-columns: 1fr 1fr; gap:0; border-top: 1px solid #e5e7eb;">
    <div style="padding: 12px 16px; border-right: 1px solid #e5e7eb; background: #ffffff;">
      <div style="font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em; color: #6b7280; margin-bottom: 8px;">{state_label}</div>
      <div id="status-summary" style="font-size: 13px; line-height: 1.6; color: #111827;">waiting for events...</div>
      <div id="governance-panel" style="margin-top: 12px; padding: 10px 12px; border-radius: 10px; background: #f3f4f6; color: #111827;">
        <div style="font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em; color: #6b7280; margin-bottom: 6px;">Harness Governance</div>
        <div id="governance-summary" style="font-size: 12px; line-height: 1.6;">No governance decision yet.</div>
      </div>
    </div>
    <div style="padding: 12px 16px; background: #fafafa;">
      <div style="font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em; color: #6b7280; margin-bottom: 8px;">Live Trace</div>
      <div id="trace-log" style="height: {height}px; overflow: auto; white-space: pre-wrap; font-size: 12px;"></div>
    </div>
  </div>
</div>
<script>
  const statusNode = document.getElementById("status-summary");
  const governanceNode = document.getElementById("governance-summary");
  const traceNode = document.getElementById("trace-log");
  const source = new EventSource("{safe_stream_url}");

  function appendTrace(line) {{
    const stamp = new Date().toLocaleTimeString();
    traceNode.textContent += `[${{stamp}}] ${{line}}\\n`;
    traceNode.scrollTop = traceNode.scrollHeight;
  }}

  function renderDecision(decision) {{
    if (!decision) return;
    const verdict = decision.allowed ? "ALLOW" : "DENY";
    const reasons = (decision.reasons || []).join(" | ") || "no reasons provided";
    const tools = (decision.allowed_tools || []).join(", ") || "none";
    governanceNode.textContent = `${{verdict}} | profile=${{decision.profile}} | risk=${{decision.risk_level}} (${{decision.risk_score}})\\n` +
      `tools: ${{tools}}\\nreasons: ${{reasons}}`;
  }}

  source.onmessage = function(event) {{
    const data = JSON.parse(event.data);
    const topic = data.topic || "";
    const payload = data.payload || {{}};

    if (topic === "ui.task.status_update") {{
      statusNode.textContent = `status=${{payload.new_status || "unknown"}}\\n${{payload.message || ""}}`;
    }} else if (topic === "sys.task.finished") {{
      statusNode.textContent = `final=${{payload.final_status || "unknown"}}\\n${{payload.message || ""}}`;
    }} else if (topic === "ui.task.governance_update") {{
      renderDecision(payload.decision);
      appendTrace(`governance => ${{JSON.stringify(payload.decision)}}`);
      return;
    }} else if (topic === "ui.task.trace_update") {{
      const traceEvent = payload.event || payload;
      const traceType = traceEvent.event_type || "unknown";
      appendTrace(`trace(${{traceType}}) => ${{JSON.stringify(traceEvent)}}`);
      return;
    }}

    appendTrace(JSON.stringify(data));
  }};

  source.onerror = function() {{
    appendTrace("stream disconnected");
  }};
</script>
"""


def render_status_stream(
    *,
    api_base_url: str,
    task_id: str = "",
    execution_id: str = "",
    tenant_id: str = "",
    workspace_id: str = "",
    api_token: str = "",
    height: int = 420,
) -> None:
    """Render the stream when Streamlit is available; otherwise raise a clear error."""
    try:
        import streamlit.components.v1 as components
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("Streamlit is not installed in the current environment") from exc

    components.html(
        build_status_stream_html(
            api_base_url=api_base_url,
            task_id=task_id,
            execution_id=execution_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            api_token=api_token,
            height=height,
        ),
        height=height + 120,
    )
