"""GL Observability Library - Use Third Party Instrumentor

This script demonstrates how to use third party instrumentors to capture traces from python libraries. This 
example will use sqlite3 library to demonstrate the functionality.

The example will use Sentry as the backend to visualize the traces.

required environment variables:
- SENTRY_DSN: The Sentry DSN
- ENVIRONMENT: The environment (e.g., staging, production)
- RELEASE: The release version
"""

import os
import httpx

from dotenv import load_dotenv
from gl_observability import (
    init_telemetry, 
    TelemetryConfig, 
    SentryBackendConfig, 
)
from opentelemetry import trace

load_dotenv()

config = {
    "sentry_dsn": os.getenv("SENTRY_DSN"),
    "environment": os.getenv("ENVIRONMENT"),
    "release": os.getenv("RELEASE"),
}

# ====================================================================
# Setup GL Observability
# ====================================================================


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
)
init_telemetry(otel_config)

# ====================================================================
# Initialize Third Party Instrumentors
# ====================================================================

import sqlite3
from opentelemetry.instrumentation.sqlite3 import SQLite3Instrumentor

# Initialize the instrumentor
SQLite3Instrumentor().instrument()

# ====================================================================
# Example usage of the instrumented library
# ====================================================================

tracer = trace.get_tracer(__name__)

with tracer.start_as_current_span("sqlite_group"):
    # Create a database and a table
    conn = sqlite3.connect("example.db")
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT)")
    conn.commit()

    # Insert some data
    cursor.execute("INSERT INTO users (name) VALUES ('John Doe')")
    conn.commit()

    # Query the data
    cursor.execute("SELECT * FROM users")
    print(cursor.fetchall())

    # Close the connection
    conn.close()

# Delete the database file
os.remove("example.db")
