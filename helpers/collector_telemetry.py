"""Small Galileo-compatible telemetry adapter for the demo Collector path.

The upstream demo uses ``GalileoLogger`` which sends directly to Galileo and
therefore expects a Galileo API token in the application process.  The EKS
deployment uses the existing OpenTelemetry Collector instead, so this adapter
implements the small logger surface used by the demo and emits OTLP spans to
the Collector.  It deliberately has no Galileo-token fallback.
"""

from __future__ import annotations

import os
import threading
from typing import Any, Optional

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, OTLPSpanExporter
from opentelemetry.trace import Span, Status, StatusCode


DEFAULT_COLLECTOR_OTLP_ENDPOINT = (
    "http://splunk-otel-collector-agent.dify.svc.cluster.local:4318/v1/traces"
)

_provider: Optional[TracerProvider] = None
_provider_lock = threading.Lock()


def _get_tracer(project_name: str, log_stream: str):
    """Return one process-wide OTLP tracer configured for this demo."""
    global _provider
    if _provider is None:
        with _provider_lock:
            if _provider is None:
                endpoint = os.environ.get(
                    "GALILEO_OTEL_ENDPOINT",
                    os.environ.get(
                        "COLLECTOR_OTLP_ENDPOINT", DEFAULT_COLLECTOR_OTLP_ENDPOINT
                    ),
                )
                resource = Resource.create(
                    {
                        "service.name": os.environ.get(
                            "OTEL_SERVICE_NAME", "galileo-golden-demo"
                        ),
                        "deployment.environment": os.environ.get(
                            "ENVIRONMENT", "demo"
                        ),
                        "galileo.project.name": project_name,
                        "galileo.logstream.name": log_stream,
                    }
                )
                provider = TracerProvider(resource=resource)
                provider.add_span_processor(
                    BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
                )
                trace.set_tracer_provider(provider)
                _provider = provider
    return trace.get_tracer("galileo-golden-demo.collector")


def _stringify(value: Any) -> str:
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    return repr(value)


class CollectorTelemetry:
    """Minimal ``GalileoLogger``-compatible object backed by OTLP."""

    def __init__(self, project_name: str, log_stream: str):
        self.project_name = project_name
        self.log_stream = log_stream
        self._tracer = _get_tracer(project_name, log_stream)
        self._trace_span: Optional[Span] = None
        self._trace_token = None
        self._session_name = ""
        self._external_id = ""

    def start_session(self, name: str = "", external_id: str = "", **_: Any) -> None:
        self._session_name = name
        self._external_id = external_id

    def start_trace(self, input: str = "", name: str = "Run Agent", **_: Any) -> None:
        if self.current_parent() is not None:
            return
        self._trace_span = self._tracer.start_span(
            name,
            attributes={
                "galileo.project.name": self.project_name,
                "galileo.logstream.name": self.log_stream,
                "galileo.session.name": self._session_name,
                "galileo.session.id": self._external_id,
                "gen_ai.prompt": _stringify(input),
            },
        )
        self._trace_token = otel_context.attach(
            trace.set_span_in_context(self._trace_span)
        )

    def current_parent(self):
        return self._trace_span

    @property
    def trace_id(self) -> str:
        if not self._trace_span:
            return ""
        return format(self._trace_span.get_span_context().trace_id, "032x")

    def _add_child_span(
        self,
        name: str,
        attributes: dict[str, Any],
        *,
        status_code: int = 200,
    ) -> None:
        parent_context = (
            trace.set_span_in_context(self._trace_span)
            if self._trace_span is not None
            else None
        )
        span = self._tracer.start_span(name, context=parent_context)
        for key, value in attributes.items():
            if value is not None:
                span.set_attribute(key, _stringify(value))
        if status_code >= 400:
            span.set_status(Status(StatusCode.ERROR))
        span.end()

    def add_llm_span(self, **kwargs: Any) -> None:
        self._add_child_span(
            kwargs.get("name", "LLM Response"),
            {
                "gen_ai.system": kwargs.get("model", ""),
                "gen_ai.request.model": kwargs.get("model", ""),
                "gen_ai.prompt": kwargs.get("input", ""),
                "gen_ai.completion": kwargs.get("output", ""),
                "gen_ai.response.model": kwargs.get("model", ""),
                "galileo.span.type": "llm",
                "galileo.metadata": kwargs.get("metadata"),
            },
            status_code=int(kwargs.get("status_code", 200)),
        )

    def add_retriever_span(self, **kwargs: Any) -> None:
        self._add_child_span(
            kwargs.get("name", "RAG Retrieval"),
            {
                "gen_ai.prompt": kwargs.get("input", ""),
                "gen_ai.retrieval.documents": kwargs.get("output", ""),
                "galileo.span.type": "retriever",
            },
            status_code=int(kwargs.get("status_code", 200)),
        )

    def add_tool_span(self, **kwargs: Any) -> None:
        self._add_child_span(
            kwargs.get("name", "Tool Call"),
            {
                "gen_ai.tool.name": kwargs.get("name", ""),
                "gen_ai.tool.input": kwargs.get("input", ""),
                "gen_ai.tool.output": kwargs.get("output", ""),
                "galileo.span.type": "tool",
            },
            status_code=int(kwargs.get("status_code", 200)),
        )

    def conclude(self, output: str = "", **_: Any) -> None:
        if self._trace_span is None:
            return
        self._trace_span.set_attribute("gen_ai.completion", _stringify(output))
        self._trace_span.end()
        if self._trace_token is not None:
            otel_context.detach(self._trace_token)
        self._trace_span = None
        self._trace_token = None

    def flush(self) -> None:
        if _provider is not None:
            _provider.force_flush()

    def enable_agent_control(self) -> None:
        """Keep the upstream call harmless; Agent Control needs a token."""

    def get_logger_instance(self):
        return self


def collector_telemetry_enabled() -> bool:
    return os.environ.get("GALILEO_TELEMETRY_MODE", "collector").strip().lower() == "collector"


def create_collector_telemetry(project_name: str, log_stream: str) -> CollectorTelemetry:
    return CollectorTelemetry(project_name, log_stream)
