# StreamGuard Quickstart
=====================

StreamGuard is a self-hosted streaming control plane that enforces correct termination, cancellation,
backpressure, and receipt-grade accounting for LLM streams.

## This demo runs a FastAPI streaming server with HTTP + WebSocket endpoints.

### 1. Start the Demo (Docker)

From the repository root:
```
docker compose -f docker/docker-compose.yml up --build
```
This will start StreamGuard on:

* `http://localhost:8000`

### 2. Test HTTP Streaming

Run:
```bash
curl "http://localhost:8000/stream?prompt=hello"
```
You should see tokens streamed back immediately.

### 3. Test WebSocket Streaming

Install websocat (if needed), then run:
```bash
websocat "ws://localhost:8000/ws?prompt=hello"
```

### 4. Metrics Endpoint

Prometheus metrics are exposed at:
```bash
curl http://localhost:8000/metrics
```

### 5. Receipts (Financial Artifact)

Every stream produces an immutable receipt written to:

* `receipts/stream_receipts.jsonl`
Each receipt includes:
* Tokens produced / committed / consumed
* Termination cause (EOS / USER cancel / SYSTEM abort)
* Accounting cutoff timestamps
* Estimated prevented token burn

### 6. Integrating Your Own Model Provider

The demo producer lives in:

* `example/ollama_producer.py`

To integrate OpenAI / Anthropic / internal LLMs:
* Implement the Producer interface
* Pass it into StreamSession

StreamGuard does not depend on any specific model vendor.
It governs stream lifecycle correctness only.