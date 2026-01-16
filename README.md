# StreamGuard: Self-Hosted LLM Streaming Cost Control & Cancellation


### Problem

LLM streaming continues **after clients disconnect**, leading to:

* Silent token burn
* Unpredictable invoices
* No audit trail
* Discovery only after the bill arrives

Most teams notice this only when finance asks questions.

### Solution: What StreamGuard Does

StreamGuard is a **self-hosted streaming control plane** that prevents token bleed during LLM streaming. It:

* Guarantees immediate cancellation on client disconnect
* Provides bounded backpressure
* Ensures strict accounting cutoffs
* Generates audit-grade receipts proving prevented spend

You keep:
* Your infrastructure
* Your API keys
* Your models
* Your data

### What StreamGuard Is Not

* Not a hosted proxy
* Not a model wrapper
* Not a prompt framework
* Not post-hoc observability

StreamGuard controls **stream lifecycle**, not prompts.

### Core Guarantees

* No token generation after client disconnect
* No unbounded buffering
* No silent accounting drift
* Deterministic shutdown
* Immutable financial receipts

All guarantees are validated against a **real streaming LLM (Ollama)**.

### Producer Model (Key Concept)

StreamGuard does **not** generate tokens. It consumes tokens from a **producer object**, which is any object that
implements a single async method:

```python
import asyncio

class MyProducer:
    async def run(
        self,
        *,
        out_q: asyncio.Queue[str],
        cancel_event: asyncio.Event,
        stats: dict,
    ) -> None:
        ...
```

The producer object is passed to a StreamSession at creation time.

### Producer Rules

* MUST stop promptly when `cancel_event` is set
* MUST emit tokens incrementally
* MUST NOT manage buffering or backpressure
* MAY raise → the stream is cancelled safely

This makes StreamGuard compatible with:

* OpenAI
* Anthropic
* Ollama
* internal LLMs

### Example: Using an Open-Source LLM (Ollama)

StreamGuard has been validated against Ollama (local, no API keys):

```python
import asyncio

producer = OllamaProducer(
    model="llama3",
    prompt="Explain backpressure in async systems.",
)

session = StreamSession(
    producer=producer,
    N=5,
    M=2,
    stats={},
)

session.start()
```

Disconnecting the client mid-stream:

* Stops token generation immediately
* Issues a receipt showing prevented spend

### Cancellation vs Shutdown

StreamGuard separates concerns intentionally:

* `cancel()`: Cuts accounting and lifecycle immediately.
* `shutdown()`: Terminates background tasks safely.

This prevents silent cost bleed while ensuring clean teardown.

### Receipts

Each stream produces an immutable receipt containing:

* Tokens produced
* Tokens committed
* Tokens consumed
* Estimated prevented tokens
* Cancellation reason and category
* Lifecycle timestamps

Receipts are financial artifacts, not logs.

### Intended Users

* B2B SaaS with chat or copilots
* Internal AI tooling teams
* Platform / infra engineers
* Teams paying real LLM invoices (if token costs matter)
