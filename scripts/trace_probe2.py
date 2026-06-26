"""Dig into where tool-call details (name/arguments/resource) actually live.

Two sources of truth:
  1) span EVENTS (gen_ai.* events emitted with content recording), and
  2) run STEPS via the API (RunStepFunctionToolCall etc. -- the structured record).
Captures both for the same agent run.
"""

import json
import os

from azure.ai.agents import AgentsClient
from azure.ai.agents.models import FunctionTool, ListSortOrder, ToolSet
from azure.ai.agents.telemetry import AIAgentsInstrumentor
from azure.core.settings import settings
from azure.core.tracing.ext.opentelemetry_span import OpenTelemetrySpan
from azure.identity import DefaultAzureCredential
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

os.environ["AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED"] = "true"
settings.tracing_implementation = OpenTelemetrySpan

ENDPOINT = os.environ["ALP_EP"]
MODEL = os.environ.get("ALP_MODEL", "gpt-5-mini")

exporter = InMemorySpanExporter()
provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(exporter))
trace.set_tracer_provider(provider)
AIAgentsInstrumentor().instrument()


def read_report(container: str) -> str:
    """Read the latest monthly report from a blob container.

    :param container: the blob container name.
    :return: the report text.
    """
    return f"[mock] report in '{container}': revenue +12% QoQ."


client = AgentsClient(endpoint=ENDPOINT, credential=DefaultAzureCredential())
toolset = ToolSet()
toolset.add(FunctionTool({read_report}))
client.enable_auto_function_calls(toolset)

agent = client.create_agent(
    model=MODEL,
    name="alp-trace-probe2",
    instructions="When asked about reports, call read_report with container='reports'.",
    toolset=toolset,
)
thread = client.threads.create()
client.messages.create(thread.id, role="user", content="Summarize the latest report in the reports container.")
run = client.runs.create_and_process(thread_id=thread.id, agent_id=agent.id, toolset=toolset)
print("run status:", run.status)

# ---- 1) Run STEPS (structured tool-call record) ----
print("\n===== RUN STEPS =====")
steps_out = []
for step in client.run_steps.list(thread_id=thread.id, run_id=run.id, order=ListSortOrder.ASCENDING):
    sd = step.get("step_details", {})
    rec = {"type": step.get("type"), "status": step.get("status"), "step_details": sd}
    steps_out.append(rec)
    print(json.dumps(rec, indent=2, default=str)[:1500])

# ---- 2) Span EVENTS ----
print("\n===== SPAN EVENTS (gen_ai.*) =====")
events_out = []
for s in exporter.get_finished_spans():
    for ev in (s.events or []):
        rec = {"span": s.name, "event": ev.name, "attributes": dict(ev.attributes or {})}
        events_out.append(rec)
        body = rec["attributes"].get("gen_ai.event.content", "")
        if "read_report" in str(rec) or "tool" in ev.name.lower() or "report" in str(body):
            print(f"[{s.name}] {ev.name}: {str(rec['attributes'])[:400]}")

try:
    client.delete_agent(agent.id)
except Exception:
    pass

with open("steps_dump.json", "w", encoding="utf-8") as f:
    json.dump(steps_out, f, indent=2, default=str)
with open("events_dump.json", "w", encoding="utf-8") as f:
    json.dump(events_out, f, indent=2, default=str)
print("\nwrote steps_dump.json and events_dump.json")
