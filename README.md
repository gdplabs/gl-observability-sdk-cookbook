# GL Observability Cookbook

A collection of production-ready examples for the [GL Observability](https://github.com/gdplabs/gl-observability-sdk) library. Each recipe is a self-contained Python script you can run directly.

## Getting Started

### Prerequisites

- Python 3.11–3.13
- [uv](https://docs.astral.sh/uv/) package manager
- Docker (required for OTLP / Jaeger examples)

### Setup

1. Clone the repository
    ```bash
    git clone https://github.com/gdplabs/gl-observability-sdk-cookbook.git
    cd gl-observability-sdk-cookbook
    ```

2. Install dependencies
    ```bash
    uv sync
    ```

3. Configure environment variables
    ```bash
    cp .env.example .env
    ```
    Edit `.env` with the values required by the recipe you want to run (see [Environment Variables](#environment-variables)).

---

## Recipes

### Traces

#### Quickstart — OTLP Backend (Jaeger)
**File:** `traces/quickstart_otlp.py`

Sends traces from a FastAPI application to any OTLP-compatible backend. The included `traces/docker-compose.yml` spins up a local Jaeger instance for testing.

```bash
# Start Jaeger
docker compose -f traces/docker-compose.yml up -d

# Run the example
uv run python traces/quickstart_otlp.py
```

Visit the Jaeger UI at `http://localhost:16686` and hit any of the sample endpoints to generate traces:

| Endpoint | Description |
|---|---|
| `GET /hello-world` | Basic trace |
| `GET /fetch-data` | Outbound HTTP call trace |
| `GET /error` | Error trace |

**Required env vars:** `OTLP_ENDPOINT`, `PROJECT_NAME`, `ENVIRONMENT`, `RELEASE`

---

#### Quickstart — Sentry Backend
**File:** `traces/quickstart_sentry.py`

Sends traces to [Sentry](https://sentry.io) using the Sentry DSN. Includes LangChain, httpx, and requests auto-instrumentation, and connects log context to traces.

```bash
uv run python traces/quickstart_sentry.py
```

**Required env vars:** `SENTRY_DSN`, `ENVIRONMENT`, `RELEASE`

---

#### Custom Sampler
**File:** `traces/sampler.py`

Demonstrates how to implement a custom `Sampler` to apply per-route sampling policies:

| Route | Sampling rate |
|---|---|
| `/important` | 100% |
| `/health`, `/not_important` | 0% |
| Everything else | 10% |

```bash
uv run python traces/sampler.py
```

**Required env vars:** `SENTRY_DSN`, `PROJECT_NAME`, `ENVIRONMENT`, `RELEASE`

---

#### Third-Party Instrumentor
**File:** `traces/third_party_instrumentor.py`

Shows how to add a third-party OpenTelemetry instrumentor (`SQLite3Instrumentor`) on top of GL Observability. All `sqlite3` calls are automatically captured as spans.

```bash
uv run python traces/third_party_instrumentor.py
```

**Required env vars:** `SENTRY_DSN`, `ENVIRONMENT`, `RELEASE`

---

### Logs

#### PII Masking — Regex Based
**File:** `logs/pii_regex_based.py`

Masks PII (emails, phone numbers) in log messages using regex patterns before they are emitted.

```bash
uv run python logs/pii_regex_based.py
```

No additional environment variables required.

---

#### PII Masking — NER API Based
**File:** `logs/pii_ner_api_based.py`

Masks PII using a Named Entity Recognition (NER) API. Calls an external API to detect entities in each log message before emitting.

```bash
uv run python logs/pii_ner_api_based.py
```

**Required env vars:** `NER_API_URL`

---

## Environment Variables

| Variable | Description | Required by |
|---|---|---|
| `ENVIRONMENT` | Deployment environment (e.g. `staging`, `production`) | All |
| `RELEASE` | Release version (e.g. `project@1.0.0+a1b2c34`) | All |
| `SENTRY_DSN` | Sentry DSN URL | Sentry examples |
| `OTLP_ENDPOINT` | OTLP HTTP endpoint (e.g. `http://localhost:4318/v1/traces`) | OTLP example |
| `PROJECT_NAME` | Service / project name | OTLP example, Sampler |
| `NER_API_URL` | NER API endpoint for PII detection | NER PII example |
