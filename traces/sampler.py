"""GL Observability Library - Sampler Example

This script demonstrates how to use a custom sampler to control trace sampling. The example
will use Sentry backend with a sampler that samples only traces from a specific route.
"""

import os
from typing import Optional, Sequence

from dotenv import load_dotenv
from fastapi import FastAPI
from gl_observability import (
    SentryBackendConfig,
    init_telemetry, 
    TelemetryConfig, 
    FastAPIConfig,
)
from opentelemetry.context import Context
from opentelemetry.sdk.trace.sampling import (
    ParentBased,
    Sampler,
    SamplingResult,
    TraceIdRatioBased,
)
from opentelemetry.trace import Link, SpanKind
from opentelemetry.trace.span import TraceState
from opentelemetry.util.types import Attributes

load_dotenv()

config = {
    "sentry_dsn": os.getenv("SENTRY_DSN"),
    "project_name": os.getenv("PROJECT_NAME"),
    "environment": os.getenv("ENVIRONMENT"),
    "release": os.getenv("RELEASE"),
}

class OtelSampler(Sampler):

    NO_SAMPLING_ENDPOINTS: set[str] = {"/health", "/not_important"}
    IMPORTANT_ENDPOINTS: set[str] = {"/important"}

    DEFAULT_SAMPLING_RATE: float = 0.1
    IMPORTANT_SAMPLING_RATE: float = 1.0
    NO_SAMPLING_RATE: float = 0.0

    def should_sample(
        self,
        parent_context: Optional[Context],
        trace_id: int,
        name: str,
        kind: SpanKind = None,
        attributes: Attributes = None,
        links: Sequence[Link] = None,
        trace_state: TraceState = None,
    ) -> SamplingResult:
        trace_sample_rate = self.DEFAULT_SAMPLING_RATE

        routes = attributes.get("http.route") if attributes else None
        if routes in self.NO_SAMPLING_ENDPOINTS:
            trace_sample_rate = self.NO_SAMPLING_RATE
        elif routes in self.IMPORTANT_ENDPOINTS:
            trace_sample_rate = self.IMPORTANT_SAMPLING_RATE

        sampler = ParentBased(TraceIdRatioBased(trace_sample_rate))
        return sampler.should_sample(
            parent_context, trace_id, name, kind, attributes, links, trace_state
        )

    def get_description(self) -> str:
        return "OtelSampler"

# ====================================================================
# Configure GL Observability
# ====================================================================

app = FastAPI()
fastapi_config = FastAPIConfig(app=app)

backend_config = SentryBackendConfig(
    dsn=config["sentry_dsn"],
    environment=config["environment"],
    release=config["release"],
    send_default_pii=True,
    disable_sentry_distributed_tracing=False
)
otel_config = TelemetryConfig(
    attributes={},
    backend_config=backend_config,
    trace_sampler=OtelSampler(),
    fastapi_config=fastapi_config,
)
init_telemetry(otel_config)

# ====================================================================
# Below are example endpoints that generate traces
# You can add more endpoints as needed
# ====================================================================

@app.get("/important")
def important():
    """Important endpoint that generates a trace."""
    return {"message": "This is an important endpoint"}

@app.get("/not-important")
def not_important():
    """Not important endpoint that generates a trace."""
    return {"message": "This is not an important endpoint"}

@app.get("/health")
def health():
    """Health endpoint that generates a trace."""
    return {"message": "OK"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)