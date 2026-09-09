"""Runtime configuration for mylib's OpenTelemetry instrumentation.

Configuration is programmatic only: an application calls ``configure()`` before
it starts using the library. Changes take effect immediately.
"""

from dataclasses import dataclass

@dataclass
class InstrumentationConfig:
    """Switches that control what mylib records.

    Attributes:
        capture_file_names: Whether spans may carry ``file.name`` and
            ``file.path``. Off by default: a file name is normally supplied by an
            end user, which makes it both unbounded in cardinality and a common
            carrier of personal data. The directory is chosen by the service, so
            ``file.directory`` is always recorded.
    """
    capture_file_names: bool = False

config = InstrumentationConfig()

def configure(
    *,
    capture_file_names: bool = False,
) -> None:
    """Change what mylib records. Takes effect immediately.

    Args:
        capture_file_names (bool): Record file names and full paths on spans. Defaults to False.

    Example:
        >>> from mylib.observability.config import configure
        >>> configure(capture_file_names=True)
    """
    config.capture_file_names = capture_file_names
