"""Live trace-schema probe (student sub).

Creates/uses an agent with a FUNCTION TOOL, runs it, and dumps the raw
OpenTelemetry span names + attributes locally (in-memory exporter) so we can see
exactly what Foundry agent tracing emits for a tool call -- which is the
load-bearing assumption behind alp's `used.py` KQL.

We also enable content recording so tool inputs/outputs appear in spans.
"""

import json
import os

from azure.ai.agents import AgentsClient
from azure.ai.agents.telemetry import AIAgentsInstrumentor
from azure.identity import DefaultAzureCredential
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

# Enable the azure-core -> OpenTelemetry bridge (required for Azure SDK spans).
from azure.core.settings import settings
from azure.core.tracing.ext.opentelemetry_span import OpenTelemetrySpan

settings.tracing_implementation = OpenTelemetrySpan

ENDPOINT = os.environ["ALP_EP"]
MODEL = os.environ.get("ALP_MODEL", "gpt-5-mini")

# record prompt/tool content in spans (off by default for privacy)
os.environ["AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED"] = "true"

exporter = InMemorySpanExporter()
provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(exporter))
trace.set_tracer_provider(provider)
AIAgentsInstrumentor().instrument()


def read_report(container: str) -> str:
    """Read the latest monthly report from a blob container.

    :param container: the blob container name to read from.
    :return: the report text.
    """
    return f"[mock] latest report in '{container}': revenue up 12% QoQ."


functions = {read_report}

client = AgentsClient(endpoint=ENDPOINT, credential=DefaultAzureCredential())

from azure.ai.agents.models import FunctionTool, ToolSet

toolset = ToolSet()
toolset.add(FunctionTool(functions))
client.enable_auto_function_calls(toolset)

agent = client.create_agent(
    model=MODEL,
    name="alp-trace-probe",
    instructions="When asked about reports, call read_report with container='reports'.",
    toolset=toolset,
)
print("agent:", agent.id)

thread = client.threads.create()
client.messages.create(thread.id, role="user", content="Summarize the latest report in the reports container.")
run = client.runs.create_and_process(thread_id=thread.id, agent_id=agent.id, toolset=toolset)
print("run status:", run.status)

# Clean up the probe agent (keep the named demo agent).
try:
    client.delete_agent(agent.id)
except Exception:
    pass

spans = exporter.get_finished_spans()
print(f"\n===== {len(spans)} SPANS CAPTURED =====")
summary = []
for s in spans:
    attrs = dict(s.attributes or {})
    summary.append({"name": s.name, "attributes": attrs})
    print(f"\n--- span: {s.name} ---")
    for k, v in attrs.items():
        vs = str(v)
        print(f"    {k} = {vs[:160]}")

with open("trace_dump.json", "w", encoding="utf-8") as f:
    json.dump(summary, f, indent=2, default=str)
print("\nwrote trace_dump.json")
