"""GL Observability Library - Quickstart Example

This script demonstrates how to initialize the GL Observability library to send
traces to Sentry backend on a FastAPI application.

required environment variables:
- SENTRY_DSN: The Sentry DSN
- ENVIRONMENT: The environment (e.g., staging, production)
- RELEASE: The release version
"""

import os
import httpx

from dotenv import load_dotenv
from fastapi import FastAPI, Response
from gl_observability import (
    init_telemetry, 
    TelemetryConfig, 
    SentryBackendConfig, 
    FastAPIConfig,
)

load_dotenv()

config = {
    "sentry_dsn": os.getenv("SENTRY_DSN"),
    "environment": os.getenv("ENVIRONMENT"),
    "release": os.getenv("RELEASE"),
}

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
    fastapi_config=fastapi_config,
    use_langchain=True,
    use_httpx=True,
    use_requests=True,
    log_trace_context=True, ## Enable this to connect log data with trace data.
)
init_telemetry(otel_config)

# ====================================================================
# Below are example endpoints that generate traces
# You can add more endpoints as needed
# ====================================================================

@app.get("/hello-world")
def hello_world():
    """Hello World endpoint that generates a trace."""
    return {"message": "Hello World"}

@app.get("/error")
def error():
    """Error endpoint that generates a trace."""
    raise Exception("This is an error message from the error endpoint")

@app.get("/fetch-data")
async def fetch_data():
    """Fetch data endpoint that generates a trace."""
    async with httpx.AsyncClient() as client:
        response = await client.get("https://example.com")
    return Response(content=response.content, status_code=response.status_code, headers=dict(response.headers))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)