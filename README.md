**StreamGuard**
================

### Self-Hosted LLM Streaming Control Plane

#### Problem

LLM streaming systems often keep producing or forwarding tokens after users disconnect. That creates:

* Silent token burn
* Buffer growth under slow consumers
* Weak cancellation attribution
* Hard-to-explain cost deltas after invoices arrive

### What StreamGuard Is

StreamGuard is a self-hosted stream lifecycle layer for token streaming systems. It:

* Does not generate tokens
* Coordinates token flow, cancellation, completion, and accounting

You keep:

* Your infrastructure
* Your API keys
* Your models
* Your data

### What StreamGuard Enforces

At protocol level, StreamGuard is built to enforce:

* Fast cancellation propagation through session, dispatcher, and producer adapter
* Bounded in-memory buffering and explicit backpressure limits
* Explicit stream completion via EOS in non-abort paths
* Accounting invariants (`produced >= committed >= consumed`)
* Per-stream receipts with lifecycle timestamps and token counts

These properties are covered by unit/integration tests in this repo and an Ollama integration example.

### What StreamGuard Does Not Claim

StreamGuard does not currently claim:

* Universal provider-side billing guarantees
* Cryptographic immutability of receipt files
* Native production adapters for every provider out of the box

### Architecture (High-Level)

StreamGuard separates responsibilities:

* Producer: emits tokens from your model/API
* ProducerAdapter: enforces cancellation-aware emission semantics
* Dispatcher: handles buffering, commit flow, and terminal transitions
* Consumer handle: reads committed tokens and emits consumption events
* Session: orchestrates lifecycle and final receipt accounting

This separation is what makes behavior inspectable and testable.

### Producer Contract

A producer implements:

```python
async def run(*, out, cancel_event) -> None:
    ...
```

Rules:

* MUST emit tokens via `out(token)`
* SHOULD stop promptly when `cancel_event` is set
* MUST NOT emit EOS
* MUST NOT manage StreamGuard accounting

Producers are wrapped by `ProducerAdapter` for protocol alignment.

### Integrations

Included now:

* Ollama streaming provider example
* FastAPI HTTP streaming endpoint
* FastAPI WebSocket endpoint

Pluggable pattern supports adding providers with the same `run(out, cancel_event)` contract.

### Cancellation and Shutdown

StreamGuard distinguishes cancellation intent from terminal shutdown:

* Client disconnect triggers cancellation intent
* Session abort path records terminal reason/category
* Shutdown acts as terminal fallback when no terminal state was observed yet

This helps reduce post-disconnect token flow and improves lifecycle attribution quality.

### End-of-Stream (EOS)

In completion paths:

* EOS is emitted once
* EOS is emitted after committed tokens are drained
* Aborted streams do not emit EOS

### Receipts

Each stream produces a receipt with:

* `produced`, `committed`, `consumed`
* `estimated_prevented`
* cancel reason/category
* lifecycle timestamps

Receipts are persisted as append-only JSONL records in the example app.

### Intended Users

Teams running production or pre-production LLM streaming workloads:

* AI platform engineers
* Infra/backend teams owning stream reliability
* Product teams needing cancellation-aware cost controls

If stream lifecycle correctness affects your cost and reliability, StreamGuard is designed for that layer.
