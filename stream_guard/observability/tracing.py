from contextvars import ContextVar
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, ConsoleSpanExporter


# ============================================================
# Tracer Initialization (EXPLICIT, NOT IMPLICIT)
# ============================================================
def init_tracing():
    provider = TracerProvider()
    provider.add_span_processor(
        SimpleSpanProcessor(ConsoleSpanExporter())
    )
    trace.set_tracer_provider(provider)


# ============================================================
# Context (READ-ONLY FOR CORE)
# ============================================================

current_stream_span: ContextVar = ContextVar(
    "current_stream_span",
    default=None,
)
