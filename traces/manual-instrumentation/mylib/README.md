# Instrumenting a Library Natively

This package is a worked example of **native (manual) instrumentation**: a library that
emits OpenTelemetry traces about its own work, without owning or configuring the telemetry.


It is to demonstrate the GL Observability SDK guide about
[manual instrumentation](https://gdplabs.gitbook.io/sdk/gl-observability/guides/traces/instrumentation#manual-instrumentation).
This README will show the thinking behind the code and explain why certain decisions were made.

---

## Only Depends on the OpenTelemetry API Side

See [`pyproject.toml`](./pyproject.toml). A library that wants to add instrumentation should only depend on the
`opentelemetry-api` package, never on `opentelemetry-sdk` or any GL Observability SDK. The API package was created
specifically to give a lightweight interface for adding instrumentation into code, without pulling in the components
that decide where telemetry is sent.

Use `opentelemetry-api>=1.0.0,<2.0.0`. Pinning to the 1.x major is a safe choice, it is already a stable standard.

```toml
# pyproject.toml

dependencies = [
    "opentelemetry-api>=1.0.0,<2.0.0",
    "opentelemetry-semantic-conventions>=0.65b0",
]
```

`opentelemetry-semantic-conventions` is the second dependency, and it is still on the API side of the line: it ships
only the generated attribute-name constants (`FileAttributes.FILE_SIZE`, `ErrorAttributes.ERROR_TYPE`), no provider,
exporter, or sampler. Depending on it buys a typo-proof spelling of every convention and a compile-time trace to the
convention a name came from. Note that its version is still pre-1.0 (`0.65b0`) and the incubating attributes it
exposes are explicitly unstable, so a library taking this dependency accepts the churn in exchange, see
[Using the incubating conventions](#using-the-incubating-conventions).


## Create Global Tracer

Each package should have one global tracer with argument name is our library name and version is the instrumentation library version.
Because we use native instrumentation, the instrumentation library version should be same with the library version. This is important
because it will be used to identify the library version in the trace data.

```python
# mylib/observability/tracer.py

from importlib.metadata import version
from opentelemetry import trace

LIBRARY_NAME = "mylib"
LIBRARY_VERSION = version(LIBRARY_NAME)

def get_tracer() -> trace.Tracer:
    """Get the tracer for this package."""
    return trace.get_tracer(LIBRARY_NAME, LIBRARY_VERSION)
```

Three things matter here:

1. **Name the tracer after the library, not the module.** The tracer name lands on 
   every span as the *instrumentation scope*, and consumers filter on it ("show me
   everything `mylib` did").
2. **Pass the version.** Reading it from installed metadata via `importlib.metadata`
   means it can never drift from the actual installed distribution. When a span looks
   wrong, the scope version tells you which release produced it.
3. **Centralise it.** One `get_tracer()` used everywhere means the naming decision is
   made once. Modules just do `tracer = get_tracer()` at import time — cheap, because
   the proxy tracer resolves the real provider lazily on first use.

## Configuration Option

A library should provide a option to configure the instrumentation if necessary. We might need to provide a custom hook to 
handle certain attributes, include or exclude an attributes, additional attributes, etc. We should focus on privacy and security
when creating instrumentation for our library. It shouldn't capture sensitive information such as API keys and PII data such
as user email, name, birth of date, citizen ID, etc. So we might have to provide an option to maybe capture those information
but by default should not.

```python
# mylib/observability/config.py

from dataclasses import dataclass

@dataclass
class InstrumentationConfig:
    """Switches that control what mylib records."""
    capture_file_names: bool = False

config = InstrumentationConfig()

def configure(
    *,
    capture_file_names: bool = False,
) -> None:
    """Change what mylib records. Takes effect immediately."""
    config.capture_file_names = capture_file_names
```

A library that configures telemetry hijacks a decision that belongs to the application
embedding it. A library that depends on the SDK forces that SDK version on every
consumer. 

You can see in our config, we only provide a configuration mechanism for our library native instrumentation, not to configure
OpenTelemetry SDK on how to handle and send the telemetry data, where it should be the application code responsibility. 
So the rule is absolute: **API only, no configuration.** Ensure to follow this approach, we have seen a few times where 
a few library configure OpenTelemetry SDK and it cause an issue.


## What Process Deserve a Span?

Spans are not free at the point of *reading*: every extra span is noise a human has to
scroll past. Instrument by value, not by coverage.

**Always instrument** — the operations that actually explain latency and failure:

- I/O: databases, caches, HTTP calls, **the filesystem**, queues, LLM requests
- Stochastic work: LLM calls, retries, feature-flag evaluation
- Subprocess execution

**Reasonable to instrument:** high-level business operations that carry attributes worth
monitoring (an order id, a tenant id).

**Do not instrument:** trivial private helpers, input validation. Use logs for those.

In `mylib` this maps directly onto the public `FileStorage` contract — `get`, `write`,
`list`, `delete` each get a span in both backends, because each one touches the disk
(`LocalFileStorage`) or the network (`S3FileStorage`). The private `_load()` helper does
**not** open a span of its own, even though it reads bytes:

```python
# mylib/file_storage/file_storage.py

def _load(self, path_obj: Path) -> File:
    """Read a file from disk. Deliberately untraced, see ``list``."""
```

The reason is `list()`: it calls `_load()` once per entry in the directory. Tracing it
would turn a single logical operation into a hundred-span fan-out that tells you nothing
`file_count` and the parent duration do not already tell you. When a helper is called in
a loop, prefer an **aggregate attribute on the parent** over a span per iteration.

`S3FileStorage` keeps the same rule for the same reason, and it is worth noting that the
fan-out there is real network traffic: `_list_keys()` pages through `list_objects_v2` and
`_load()` issues one `get_object` per key. `mylib` still adds no span per key — but this
is exactly the case where the botocore instrumentation earns its keep, because the child
`CLIENT` spans it emits give you the per-request detail without `mylib` inventing a
parallel set of its own.

## Create Spans with a Context Manager

The context-manager form is the default because it cannot leak a span: it ends on the
way out of the block whether that exit is a return or an exception.

```python
# mylib/file_storage/file_storage.py

with tracer.start_as_current_span(
    "get file",
    attributes=self._operation_attributes("get", path_obj)
) as span:
    ...
```

Note that attributes known *up front* are passed to `start_as_current_span` rather than
set afterwards with `span.set_attribute`. This is not cosmetic: **sampling decisions are
made when the span starts.** An attribute added later cannot influence whether the span
is kept, so anything a sampler might want to see must be present at creation time.

Attributes only knowable *after* the work are set on the span afterwards — which is
exactly what `get` does with the file size:

```python
# mylib/file_storage/file_storage.py

    span.set_attribute(FileAttributes.FILE_SIZE, file.metadata.size)
```

The SDK also offers a decorator form (`@tracer.start_as_current_span("...")`) and a
manual `start_span()` / `context.attach()` / `span.end()` form. The decorator is fine
when a function body maps 1:1 to a span and needs no dynamic attributes; the manual form
is for spans whose lifetime crosses function boundaries (a background task, a streaming
response). Reach for them only when the context manager genuinely does not fit.

### Span kind

`LocalFileStorage` writes to local disk, so the work happens in-process and its spans
stay `INTERNAL` (the default). `S3FileStorage` calls out to another system, so a `CLIENT`
span belongs in the trace — but `mylib` does not create it. Its spans are `INTERNAL` too:

```python
# mylib/file_storage/s3_storage.py

class S3FileStorage(FileStorage):
    # Spans stay INTERNAL and carry only what this library knows. The CLIENT
    # span for the S3 call itself -- ``rpc.*``, ``aws.s3.*``, retries, request
    # ids -- comes from ``opentelemetry-instrumentation-botocore``, which sees
    # the wire and so describes it better than this layer could.
```

The `CLIENT` span arrives as a *child*, from `opentelemetry-instrumentation-botocore`.
That instrumentation sits on the wire, so it knows things this layer cannot: the HTTP
status, `aws.request_id`, and how many retries a single `put_object` really cost. Marking
the `mylib` span `CLIENT` as well would produce two `CLIENT` spans for one call, and the
less accurate of the two would be ours.

The rule generalises: **let the lowest layer that actually performs the I/O own the
`CLIENT` span.** A library wrapping an instrumented client stays `INTERNAL` and
contributes only domain meaning — here `mylib.file_storage.operation` and the `file.*`
attributes — leaving transport detail to the layer that can see it.

Pick the kind by where the work happens, not by how the method feels: `CLIENT` when you
call out to another system, `SERVER` when you handle an inbound request, `PRODUCER` /
`CONSUMER` for queues, `INTERNAL` otherwise.

## Naming spans

`mylib` uses `"get file"`, `"write file"`, `"list files"`, `"delete file"` — a fixed set
of four, with the path carried in attributes rather than baked into the name. The name should
be `{verb} {object}`. Something declarative and narative.

The one thing you must never do is interpolate a variable into a span name:

```python
# Never do this — one span name per file, and your backend's index explodes.
with tracer.start_as_current_span(f"get {path}"):
    ...

# Intead do this
with tracer.start_as_current_span("get file", attributes={"file.path": path}):
    ...
```

## Naming attributes 

Attributes are where the high-cardinality detail belongs. Their naming follows a
priority order:

1. **Use an existing OpenTelemetry semantic convention if one exists.** `mylib` records
   `file.directory`, `file.extension`, `file.name`, `file.path`, `file.size` — all from
   the standard `file.*` conventions — plus `error.type` on failure. This is what makes
   your spans legible to tooling and dashboards that were never written with your library
   in mind.
2. **Otherwise, namespace under your library name.** Anything without a convention gets
   the `mylib.file_storage.*` prefix: `mylib.file_storage.operation`,
   `mylib.file_storage.storage_type`, `mylib.file_storage.file_count`. Prefixing prevents
   your library from colliding with the application's own attributes, or with another
   library's.
3. **Dots separate namespaces; snake_case within a segment.** `app.cache.hit`, not
   `app_cache_hit`.
4. **Name the entity, not the bare field.** `user.id`, not `id`.
5. **Plural for arrays, singular otherwise.** `app.order.items.ids` holds a list.

That is why the attributes are named as they are in the example below:

```python
# mylib/file_storage/file_storage.py (simplified)

from opentelemetry.semconv._incubating.attributes import file_attributes as FileAttributes

def write(self, path: str, file: File) -> None:
    attributes = {
        "mylib.file_storage.operation": "write",
        "mylib.file_storage.storage_type": "local",
        FileAttributes.FILE_SIZE: len(file.content),
        ...
    }
    with tracer.start_as_current_span("write file", attributes=attributes) as span:
        ...
```

### Use the constants, not the string literals

Note the import. A convention attribute is spelled through the constant
`FileAttributes.FILE_SIZE` rather than the literal `"file.size"`, and the same goes for
`ErrorAttributes.ERROR_TYPE`. The value is identical — the benefit is that a typo becomes
an `AttributeError` at import time instead of an attribute silently landing under a name
no dashboard queries, and that a reader can jump from the constant to the convention that
defines it. Your own namespaced attributes have no constants to import, so they stay
literals; keep them in one place (here, `_operation_attributes`) so the prefix is written
once.

### Using the incubating conventions

`file.*` currently lives under `opentelemetry.semconv._incubating`. The leading underscore
and the package's pre-1.0 version are a deliberate warning: incubating attributes may be
renamed or removed in a minor release, and the import path itself is not a stable API.

That is a real cost for a library, because your attribute names are a contract with your
consumers (see [Publish what you emit](#publish-what-you-emit)). Take the dependency
knowing that: pin the semconv package, watch its changelog, and treat a convention rename
upstream as a breaking change to your own telemetry that you version and document — not
as a patch you ship quietly. The alternative, hardcoding `"file.size"` as a literal, does
not actually avoid the churn; it just hides it from you until a dashboard goes blank.

## Privacy by default, Configurable by the Application

This is the requirement most often skipped, and the one most likely to cause a real
incident. A library must not put user data into telemetry unless the application has
asked it to.

`mylib` treats a file *name* as user data and a *directory* as service data:

```python
# mylib/file_storage/file_storage.py

def _file_attributes(path_obj: Path) -> dict[str, Any]:
    attributes: dict[str, Any] = {FileAttributes.FILE_DIRECTORY: str(path_obj.parent)}
    if path_obj.suffix:
        attributes[FileAttributes.FILE_EXTENSION] = path_obj.suffix.lstrip(".")
    if config.capture_file_names:
        attributes[FileAttributes.FILE_NAME] = path_obj.name
        attributes[FileAttributes.FILE_PATH] = str(path_obj)
    return attributes
```

The reason is that a file name is normally supplied by an end user, which makes it both
unbounded in cardinality and a common carrier of personal data. The directory is chosen
by the service, so `file.directory` is always recorded.

`S3FileStorage` applies the identical rule to object keys in `_key_attributes()`, walking
the key with `PurePosixPath` instead of `Path` so that the parsing does not change with
the operating system the library happens to run on. The important part is that the
*policy* is one decision applied in both backends: a new storage backend that skipped the
opt-in check would quietly become the leak, so the gate belongs in whatever helper builds
`file.*` attributes, never at the call sites.

The escape hatch is an explicit, programmatic opt-in — `mylib/observability/config.py`:

```python
# mylib/observability/config.py

@dataclass
class InstrumentationConfig:
    capture_file_names: bool = False

config = InstrumentationConfig()

def configure(*, capture_file_names: bool = False) -> None:
    """Change what mylib records. Takes effect immediately."""
    config.capture_file_names = capture_file_names
```

Design notes: keyword-only arguments keep call sites self-documenting and let you add
switches without breaking anyone; module-level state is read at span-creation time so
changes take effect immediately; and the default of every switch is the private one.
Reading the flag inside `_file_attributes` (rather than caching it at import) is what
makes "takes effect immediately" true.

## Record Errors so We Can Analyze Them

An exception explains an error, so a span that fails should say so. What a span needs to
carry, though, is only the part a dashboard queries: the failed status and a
low-cardinality error type. The detail — the stack trace — is better recorded as a log,
because span events are being deprecated in favour of the logs signal.

`mylib` centralises the span half of that in one helper:

```python
# mylib/file_storage/file_storage.py (identical in s3_storage.py)

def _record_failure(self, span: Span, error: Exception) -> None:
    """Mark the span as failed.

    The status and ``error.type`` are what dashboards and sampling decisions
    read. The stack trace is deliberately left to the application's logger
    rather than written to a span event, because span events are being
    deprecated in favour of logs.
    """
    span.set_status(Status(StatusCode.ERROR, str(error)))
    span.set_attribute(ErrorAttributes.ERROR_TYPE, type(error).__qualname__)
```

Note what the helper does *not* do: it never calls `span.record_exception()`, and it does
no logging of its own. That is the same boundary as everywhere else in this guide — the
library marks the span and re-raises, and the application, which owns the logging
configuration, decides how the traceback is recorded. Because the log record is emitted
inside the active span's context, it is correlated to this span by trace and span id
anyway, so nothing is lost by leaving it to the caller.

Used at every call site the same way — **record, then re-raise**:

```python
# mylib/file_storage/file_storage.py

try:
    file = self._load(path_obj)
except OSError as error:
    self._record_failure(span, error)
    raise
```

The four rules embedded here:

- **`set_status(StatusCode.ERROR)`** is what makes the span show as failed. Without it a
  span that raised looks identical to one that succeeded.
- **`error.type`** is a low-cardinality semantic-convention attribute — the class name,
  not the message. It is what you group an error-rate chart by. The message goes in the
  status description, where high cardinality is tolerated.
- **Never swallow the exception.** Instrumentation observes behaviour; it must not
  change it. The bare `raise` preserves the original traceback.
- **Stack traces belong in logs**, not in span events. Span events are being deprecated
  in favour of the logs signal; a log record correlated by trace id carries the same
  information without bloating the span.

Also note that "expected" failures are not errors. `delete` tolerates a missing file
when reading its size, and does not mark the span failed for it:

```python
# mylib/file_storage/file_storage.py

try:
    size = path_obj.stat().st_size
    span.set_attribute(FileAttributes.FILE_SIZE, size)
except Exception:
    pass

# mylib/file_storage/s3_storage.py -- same idea over the network:
# a HEAD request issued purely to enrich the span
try:
    head = self._client.head_object(Bucket=self._bucket, Key=path)
    span.set_attribute(FileAttributes.FILE_SIZE, head["ContentLength"])
except Exception:
    pass
```

Only mark a span as an error when the *operation* failed. A cache miss, a 404 on an
optional lookup, or an absent optional attribute is a normal outcome. Both blocks above
exist only to enrich the span, so their failure must not colour the operation — and note
that swallowing is acceptable here precisely because nothing but an attribute depends on
the result. The `unlink()` / `delete_object()` call that follows is the actual operation,
and its failure is recorded and re-raised.

The cost is worth stating: on S3 that best-effort `head_object` is an extra round trip on
every delete, paid so the span can carry `file.size`. That is a reasonable trade for a
cookbook example, and a deliberate decision — not a free one — in a hot path.

## Publish what you emit

Everything above becomes a **contract** the moment someone builds an alert on it. If you
rename a span or drop an attribute, their dashboard breaks silently. Document the
emitted telemetry in your public docs and treat changes to it as versioned API changes.

For `mylib` that contract is the same for both backends — only the value of
`mylib.file_storage.storage_type` differs (`local` or `s3`):

| Span | Kind | Attributes |
| --- | --- | --- |
| `get file` | INTERNAL | `mylib.file_storage.operation`, `mylib.file_storage.storage_type`, `file.directory`, `file.extension`, `file.size` *(set after the read)*, *(opt-in)* `file.name`, `file.path` |
| `write file` | INTERNAL | same, except `file.size` is known up front and set at span creation |
| `list files` | INTERNAL | `mylib.file_storage.operation`, `mylib.file_storage.storage_type`, `file.directory`, `mylib.file_storage.file_count` *(set after the listing)* |
| `delete file` | INTERNAL | `mylib.file_storage.operation`, `mylib.file_storage.storage_type`, `file.directory`, `file.extension`, `file.size` *(best effort)*, *(opt-in)* `file.name`, `file.path` |

`file.extension` is only present when the path or key actually has a suffix, and the two
opt-in attributes appear only when the application has called
`configure(capture_file_names=True)`. On failure, every span additionally carries
`error.type` and an `ERROR` status.

Under `S3FileStorage` these spans are parents, not leaves: the `CLIENT` spans for the
underlying `get_object`, `put_object`, `list_objects_v2` and `delete_object` calls are
contributed by `opentelemetry-instrumentation-botocore` when the application enables it.
That is worth documenting too, because it tells a consumer which half of the trace comes
from you — and therefore which half you can promise not to break.

## Checklist

Before shipping native instrumentation:

- [ ] Telemetry dependencies are API-side only (`opentelemetry-api`, optionally `opentelemetry-semantic-conventions` and `opentelemetry-semantic-conventions-ai` for Gen AI if your library is a Gen AI library) — no SDK, no GL Observability SDK
- [ ] The library never creates a `TracerProvider`, exporter, or sampler
- [ ] Convention attribute names come from semconv constants, not string literals, and any incubating ones are a known, pinned risk
- [ ] The tracer is named after the package and carries the installed version
- [ ] Spans exist for I/O, stochastic work, and subprocesses — not for trivial helpers
- [ ] No helper called in a loop opens its own span; the parent carries a count instead
- [ ] Span names are low-cardinality and contain no interpolated values
- [ ] Attributes reuse OTel semantic conventions where they exist, and are namespaced where they do not
- [ ] No `None` reaches `set_attribute`
- [ ] Attributes needed for sampling are set at span creation, not after
- [ ] User-supplied data is off by default and gated behind explicit configuration
- [ ] Failures set an `ERROR` status and `error.type`, and re-raise unchanged
- [ ] Best-effort enrichment that fails does not mark the operation as failed
- [ ] Every backend routes its attributes through the same helper, so the privacy gate cannot be bypassed by a new implementation
- [ ] Span names and attributes are documented as a public contract

## References

- [GL Observability — Instrumentation guide](https://gdplabs.gitbook.io/sdk/gl-observability/guides/traces/instrumentation#manual-instrumentation)
- [OpenTelemetry semantic conventions](https://opentelemetry.io/docs/specs/semconv/)
- [Semantic conventions — `file.*` attributes](https://opentelemetry.io/docs/specs/semconv/registry/attributes/file/)
- [Semantic conventions — `error.type`](https://opentelemetry.io/docs/specs/semconv/registry/attributes/error/)
- [OpenTelemetry Python — manual instrumentation](https://opentelemetry.io/docs/languages/python/instrumentation/)
- [`opentelemetry-instrumentation-botocore`](https://opentelemetry-python-contrib.readthedocs.io/en/latest/instrumentation/botocore/botocore.html)
