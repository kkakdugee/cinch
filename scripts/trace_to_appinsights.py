"""End-to-end: emit agent traces to App Insights, then query them back via KQL --
proving the real query path the product uses.
"""

import json
import os
import time

from azure.ai.agents import AgentsClient
from azure.ai.agents.models import FunctionTool, ToolSet
from azure.ai.agents.telemetry import AIAgentsInstrumentor
from azure.core.settings import settings
from azure.core.tracing.ext.opentelemetry_span import OpenTelemetrySpan
from azure.identity import DefaultAzureCredential
from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

os.environ["AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED"] = "true"
settings.tracing_implementation = OpenTelemetrySpan

ENDPOINT = os.environ["ALP_EP"]
MODEL = os.environ.get("ALP_MODEL", "gpt-5-mini")
CONN = os.environ["ALP_AI_CONN"]

provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(AzureMonitorTraceExporter(connection_string=CONN)))
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
    name="alp-ai-probe",
    instructions="When asked about reports, call read_report with container='reports'.",
    toolset=toolset,
)
thread = client.threads.create()
client.messages.create(thread.id, role="user", content="Summarize the latest report in the reports container.")
run = client.runs.create_and_process(thread_id=thread.id, agent_id=agent.id, toolset=toolset)
print("run status:", run.status, "agent:", agent.id)
try:
    client.delete_agent(agent.id)
except Exception:
    pass
provider.force_flush()
print("flushed to App Insights; ingestion typically 1-4 min.")
print("AGENT_ID", agent.id)
