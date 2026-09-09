from datetime import datetime, timezone
import mimetypes

from pathlib import PurePosixPath
from typing import Any

from mylib.file_storage.base import File, FileMetadata, FileStorage
from mylib.observability.config import config
from mylib.observability.tracer import get_tracer
from opentelemetry.trace import Span, Status, StatusCode
from opentelemetry.semconv.attributes import error_attributes as ErrorAttributes
from opentelemetry.semconv._incubating.attributes import file_attributes as FileAttributes

tracer = get_tracer()


def _key_attributes(key: str) -> dict[str, Any]:
    """Describe an object key using the OpenTelemetry ``file.*`` conventions.

    Only the key prefix is recorded by default. See
    ``InstrumentationConfig.capture_file_names`` for why the name and the full
    key are opt-in.
    """
    key_obj = PurePosixPath(key)
    attributes: dict[str, Any] = {FileAttributes.FILE_DIRECTORY: str(key_obj.parent)}
    if key_obj.suffix:
        attributes[FileAttributes.FILE_EXTENSION] = key_obj.suffix.lstrip(".")
    if config.capture_file_names:
        attributes[FileAttributes.FILE_NAME] = key_obj.name
        attributes[FileAttributes.FILE_PATH] = key
    return attributes


class S3FileStorage(FileStorage):
    """File storage backed by an S3 bucket."""

    # Spans stay INTERNAL and carry only what this library knows. The CLIENT
    # span for the S3 call itself -- ``rpc.*``, ``aws.s3.*``, retries, request
    # ids -- comes from ``opentelemetry-instrumentation-botocore``, which sees
    # the wire and so describes it better than this layer could.
    _STORAGE_TYPE = "s3"

    def __init__(
        self,
        client: Any,
        bucket: str,
    ) -> None:
        """Create a storage bound to one bucket.

        Args:
            client: A boto3 S3 client, e.g. ``boto3.client("s3")``.
            bucket (str): Name of the S3 bucket.
        """
        self._client = client
        self._bucket = bucket

    def get(self, path: str) -> File:
        """Get a file from the storage."""
        with tracer.start_as_current_span(
            "get file",
            attributes=self._operation_attributes("get", path),
        ) as span:
            try:
                response = self._client.get_object(Bucket=self._bucket, Key=path)
                file = self._to_file(path, response, response["Body"].read())
            except Exception as error:
                self._record_failure(span, error)
                raise

            span.set_attribute(FileAttributes.FILE_SIZE, file.metadata.size)
            return file

    def write(self, path: str, file: File) -> None:
        """Write a file to the storage."""
        attributes = self._operation_attributes("write", path)
        attributes[FileAttributes.FILE_SIZE] = len(file.content)

        with tracer.start_as_current_span("write file", attributes=attributes) as span:
            mime_type = file.metadata.mime_type
            if mime_type is None:
                mime_type, _ = mimetypes.guess_type(path)
                
            extra: dict[str, Any] = {}
            if mime_type is not None:
                extra["ContentType"] = mime_type

            try:
                self._client.put_object(
                    Bucket=self._bucket, Key=path, Body=file.content, **extra
                )
            except Exception as error:
                self._record_failure(span, error)
                raise

    def list(self, path: str) -> list[File]:
        """List files under a key prefix."""
        prefix = path
        if prefix and not prefix.endswith("/"):
            prefix += "/"

        with tracer.start_as_current_span(
            "list files",
            attributes={
                "mylib.file_storage.operation": "list",
                "mylib.file_storage.storage_type": self._STORAGE_TYPE,
                FileAttributes.FILE_DIRECTORY: prefix.rstrip("/"),
            },
        ) as span:
            try:
                keys = self._list_keys(prefix)
                loaded = [self._load(key) for key in keys]
            except Exception as error:
                self._record_failure(span, error)
                raise

            span.set_attributes({
                "mylib.file_storage.file_count": len(loaded),
            })
            return loaded

    def delete(self, path: str) -> None:
        """Delete file from storage. Deleting a missing file is not an error."""
        with tracer.start_as_current_span(
            "delete file",
            attributes=self._operation_attributes("delete", path),
        ) as span:
            try:
                head = self._client.head_object(Bucket=self._bucket, Key=path)
                span.set_attribute(FileAttributes.FILE_SIZE, head["ContentLength"])
            except Exception:
                pass

            try:
                self._client.delete_object(Bucket=self._bucket, Key=path)
            except Exception as error:
                self._record_failure(span, error)
                raise

    def _operation_attributes(self, operation: str, key: str) -> dict[str, Any]:
        return {
            "mylib.file_storage.operation": operation,
            "mylib.file_storage.storage_type": self._STORAGE_TYPE,
            **_key_attributes(key),
        }

    def _record_failure(self, span: Span, error: Exception) -> None:
        """Mark the span as failed and emit the detail as a log.

        The status and ``error.type`` are what dashboards and sampling decisions
        read. The stack trace goes to the logger rather than to a span event,
        because span events are being deprecated in favour of logs.
        """
        span.set_status(Status(StatusCode.ERROR, str(error)))
        span.set_attribute(ErrorAttributes.ERROR_TYPE, type(error).__qualname__)

    def _list_keys(self, prefix: str) -> "list[str]":
        """Page through every object key under ``prefix``, directories aside."""
        paginator = self._client.get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=self._bucket, Prefix=prefix)
        return [
            obj["Key"]
            for page in pages
            for obj in page.get("Contents", [])
            if not obj["Key"].endswith("/")
        ]

    def _load(self, key: str) -> File:
        """Fetch one object. Deliberately untraced, see ``list``."""
        response = self._client.get_object(Bucket=self._bucket, Key=key)
        return self._to_file(key, response, response["Body"].read())

    def _to_file(self, key: str, response: dict[str, Any], content: bytes) -> File:
        """Build a ``File`` from a ``get_object`` response.

        S3 records no creation time, so ``created_at`` mirrors the last
        modification.
        """
        modified = response.get("LastModified") or datetime.now(timezone.utc)
        mime = response.get("ContentType")
        if mime is None:
            mime, _ = mimetypes.guess_type(key)

        return File(
            name=PurePosixPath(key).name,
            content=content,
            metadata=FileMetadata(
                created_at=modified,
                updated_at=modified,
                size=response.get("ContentLength", len(content)),
                mime_type=mime,
            ),
        )
