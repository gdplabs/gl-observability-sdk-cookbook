from datetime import datetime, timezone
import mimetypes

from pathlib import Path
from typing import Any

from mylib.file_storage.base import File, FileMetadata, FileStorage
from mylib.observability.config import config
from mylib.observability.tracer import get_tracer
from opentelemetry.trace import Span, Status, StatusCode
from opentelemetry.semconv.attributes import error_attributes as ErrorAttributes
from opentelemetry.semconv._incubating.attributes import file_attributes as FileAttributes

tracer = get_tracer()


def _file_attributes(path_obj: Path) -> dict[str, Any]:
    """Describe a file using the OpenTelemetry ``file.*`` semantic conventions.

    Only the directory is recorded by default. See
    ``InstrumentationConfig.capture_file_names`` for why the name and the full
    path are opt-in.
    """
    attributes: dict[str, Any] = {FileAttributes.FILE_DIRECTORY: str(path_obj.parent)}
    if path_obj.suffix:
        attributes[FileAttributes.FILE_EXTENSION] = path_obj.suffix.lstrip(".")
    if config.capture_file_names:
        attributes[FileAttributes.FILE_NAME] = path_obj.name
        attributes[FileAttributes.FILE_PATH] = str(path_obj)
    return attributes


class LocalFileStorage(FileStorage):
    """Local file storage implementation."""

    # Spans stay INTERNAL because the work happens in this process. An
    # implementation backed by S3 or GCS would use SpanKind.CLIENT instead.
    _STORAGE_TYPE = "local"

    def get(self, path: str) -> File:
        """Get a file from the storage."""
        path_obj = Path(path)
        with tracer.start_as_current_span(
            "get file",
            attributes=self._operation_attributes("get", path_obj),
        ) as span:
            try:
                file = self._load(path_obj)
            except OSError as error:
                self._record_failure(span, error)
                raise

            span.set_attribute(FileAttributes.FILE_SIZE, file.metadata.size)
            return file

    def write(self, path: str, file: File) -> None:
        """Write a file to the storage."""
        path_obj = Path(path)
        attributes = self._operation_attributes("write", path_obj)
        attributes[FileAttributes.FILE_SIZE] = len(file.content)

        with tracer.start_as_current_span("write file", attributes=attributes) as span:
            try:
                path_obj.write_bytes(file.content)
            except OSError as error:
                self._record_failure(span, error)
                raise

    def list(self, path: str) -> list[File]:
        """List files in the storage."""
        path_obj = Path(path)
        with tracer.start_as_current_span(
            "list files",
            attributes={
                "mylib.file_storage.operation": "list",
                "mylib.file_storage.storage_type": self._STORAGE_TYPE,
                FileAttributes.FILE_DIRECTORY: str(path_obj),
            }
        ) as span:
            try:
                files = [entry for entry in path_obj.iterdir() if entry.is_file()]
                loaded = [self._load(entry) for entry in files]
            except OSError as error:
                self._record_failure(span, error)
                raise

            span.set_attributes({
                "mylib.file_storage.file_count": len(loaded),
            })
            return loaded

    def delete(self, path: str) -> None:
        """Delete file from storage. Deleting a missing file is not an error."""
        path_obj = Path(path)
        with tracer.start_as_current_span(
            "delete file",
            attributes=self._operation_attributes("delete", path_obj)
        ) as span:
            try:
                size = path_obj.stat().st_size
                span.set_attribute(FileAttributes.FILE_SIZE, size)
            except Exception as error:
                pass

            try:
                path_obj.unlink()
            except Exception as error:
                self._record_failure(span, error)
                raise


    def _operation_attributes(self, operation: str, path_obj: Path) -> dict[str, Any]:
        return {
            "mylib.file_storage.operation": operation,
            "mylib.file_storage.storage_type": self._STORAGE_TYPE,
            **_file_attributes(path_obj),
        }

    def _record_failure(self, span: Span, error: Exception) -> None:
        """Mark the span as failed and emit the detail as a log.

        The status and ``error.type`` are what dashboards and sampling decisions
        read. The stack trace goes to the logger rather than to a span event,
        because span events are being deprecated in favour of logs.
        """
        span.set_status(Status(StatusCode.ERROR, str(error)))
        span.set_attribute(ErrorAttributes.ERROR_TYPE, type(error).__qualname__)

    def _load(self, path_obj: Path) -> File:
        """Read a file from disk. Deliberately untraced, see ``list``."""
        st = path_obj.stat()
        mime, _ = mimetypes.guess_type(path_obj.name)
        content = path_obj.read_bytes()

        return File(
            name=path_obj.name,
            content=content,
            metadata=FileMetadata(
                created_at=datetime.fromtimestamp(
                    getattr(st, "st_birthtime", st.st_mtime),
                    timezone.utc
                ),
                updated_at=datetime.fromtimestamp(st.st_mtime, timezone.utc),
                size=st.st_size,
                mime_type=mime
            )
        )