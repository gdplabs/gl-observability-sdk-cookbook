"""Tracer configuration for the mylib package."""

from importlib.metadata import version
from opentelemetry import trace


LIBRARY_NAME = "mylib"
LIBRARY_VERSION = version(LIBRARY_NAME)

def get_tracer() -> trace.Tracer:
    """Get the tracer for this package."""
    return trace.get_tracer(LIBRARY_NAME, LIBRARY_VERSION)
