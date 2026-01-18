**StreamGuard**
================

### Self-Hosted LLM Streaming Control Plane

#### Problem

LLM streaming systems often continue generating or committing tokens after clients disconnect, leading to:

* Silent token burn
* Unbounded buffering under slow consumers
* Inaccurate or delayed cost attribution
* Discovery only after invoices arrive

Most teams notice the problem only when finance escalates.

### What StreamGuard Is

StreamGuard is a self-hosted streaming control plane that enforces correct lifecycle semantics for LLM token
streams. It:

* Does not generate tokens
* Governs how tokens flow, terminate, and are accounted for

You keep:

* Your infrastructure
* Your API keys
* Your models
* Your data

### What StreamGuard Guarantees

StreamGuard enforces the following protocol-level guarantees:

* Hard accounting cutoff after cancellation or shutdown
* No token commitment after cutoff, even if producers misbehave
* Bounded buffering and backpressure during streaming
* Explicit, deterministic stream completion (EOS)
* No ACK-dependent deadlocks (slow consumers are safe)
* Correct attribution of termination cause
* Immutable, auditable receipts

These guarantees are validated against real streaming LLMs (Ollama) and enforced by tests, not heuristics.

### What StreamGuard Is Not

Not a:

* Hosted proxy
* Model wrapper
* Prompt framework
* Post-hoc observability

StreamGuard controls stream lifecycle, not prompts or model internals.

### Architecture (High-Level)

StreamGuard separates responsibilities explicitly:

* Producer: generates tokens (LLM, API, or internal system)
* Dispatcher: enforces backpressure, ordering, and finalization
* Consumer: reads committed tokens
* Protocol: defines cancellation, completion, and correctness
* Session: orchestrates lifecycle and accounting

This separation is what makes correctness provable.

### Producer Model

A producer is any object implementing:

```python
async def run(*, out, cancel_event) -> None:
    ...
```

Rules:

* MUST emit tokens via `out(token)`
* MUST stop promptly when `cancel_event` is set
* MUST NOT emit EOS
* MUST NOT manage buffering or accounting
* MAY raise → stream aborts safely

Producers are wrapped by an adapter that enforces protocol semantics.

### Compatible with:

* Ollama
* OpenAI-style streaming
* Anthropic-style streaming
* Internal LLMs

### Example: Streaming with Ollama
```python
producer = OllamaProducer(
    model="llama3",
    prompt="Explain backpressure in distributed systems.",
)

session = StreamSession(
    producer=producer,
    speculative_buffer_limit=8,
    max_inflight_commits=16,
)

session.start()
```

### Cancellation vs Shutdown (Important)

StreamGuard distinguishes intent from authority:

* Client disconnect → protocol-level cancellation intent
* Protocol cancellation → authoritative abort with USER attribution
* Shutdown → authoritative fallback if nothing else has terminated the stream

Shutdown never overrides an existing terminal cause.

This prevents silent cost bleed while preserving correct attribution.

### End-of-Stream (EOS)

Stream completion is explicit.

* EOS is emitted exactly once
* EOS does not depend on consumer ACKs
* EOS is delivered after all committed tokens

Consumers must stop reading on EOS.

### Receipts

Each stream produces an immutable receipt containing:

* Tokens produced
* Tokens committed
* Tokens consumed
* Estimated prevented tokens
* Termination reason and category
* Lifecycle timestamps

Receipts are financial artifacts, not logs.

### Intended Users

B2B SaaS with chat or copilots

* Internal AI tooling teams
* Platform / infra engineers
* Teams paying real LLM invoices

If token costs matter, lifecycle correctness matters.
