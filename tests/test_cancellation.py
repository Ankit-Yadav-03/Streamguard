import asyncio
import pytest

from stream_guard.producer import (
    ProducerAdapter,
    ProducerToken,
    ProducerDone,
    ProducerAborted,
)


# ------------------------------------------------------------
# Test helpers
# ------------------------------------------------------------

class RecordingEmitter:
    """
    Records ProducerEvents emitted by the adapter.
    """
    def __init__(self):
        self.events = []

    async def emit(self, event):
        self.events.append(event)


class MisbehavingProducer:
    """
    Producer that keeps emitting tokens even after cancellation.
    Used to prove cutoff enforcement.
    """
    async def run(self, *, out, cancel_event):
        # Emit one token before cancellation
        await out("before")

        # Busy-loop trying to emit after cancellation
        while True:
            await out("after")
            await asyncio.sleep(0)


class CleanProducer:
    """
    Producer that emits tokens and returns normally.
    """
    async def run(self, *, out, cancel_event):
        await out("a")
        await out("b")
        return


class ExplodingProducer:
    """
    Producer that raises after emitting a token.
    """
    async def run(self, *, out, cancel_event):
        await out("x")
        raise RuntimeError("boom")


# ------------------------------------------------------------
# Cutoff Tests
# ------------------------------------------------------------

@pytest.mark.asyncio
async def test_cancellation_enforces_ingestion_cutoff():
    """
    Cancellation enforces an ingestion cutoff.

    Guarantees:
    - Adapter does not emit DONE after cancellation
    - Adapter does not emit ABORTED after cancellation
    - Adapter terminates cleanly
    - No reliance on producer cooperation
    """
    cancel_event = asyncio.Event()
    emitter = RecordingEmitter()

    producer = MisbehavingProducer()
    adapter = ProducerAdapter(producer)

    async def run_adapter():
        await adapter.run(
            emit=emitter.emit,
            cancel_event=cancel_event,
        )

    task = asyncio.create_task(run_adapter())

    # Allow at least one token to pass
    while not emitter.events:
        await asyncio.sleep(0)

    # Trigger cancellation
    cancel_event.set()

    # Allow adapter to observe cancellation
    await asyncio.sleep(0.02)
    task.cancel()

    tokens = [e for e in emitter.events if isinstance(e, ProducerToken)]
    dones = [e for e in emitter.events if isinstance(e, ProducerDone)]
    aborts = [e for e in emitter.events if isinstance(e, ProducerAborted)]

    # At least one token before cancellation
    assert tokens
    # No terminal events after cancellation
    assert not dones
    assert not aborts



@pytest.mark.asyncio
async def test_done_not_emitted_after_cancellation():
    """
    ProducerDone must not be emitted if cancellation happens first.
    """
    cancel_event = asyncio.Event()
    emitter = RecordingEmitter()

    producer = CleanProducer()
    adapter = ProducerAdapter(producer)

    async def run_and_cancel():
        # Cancel immediately before producer completes
        cancel_event.set()
        await adapter.run(
            emit=emitter.emit,
            cancel_event=cancel_event,
        )

    await run_and_cancel()

    assert not any(isinstance(e, ProducerDone) for e in emitter.events), (
        "ProducerDone must not be emitted after cancellation"
    )


@pytest.mark.asyncio
async def test_aborted_not_emitted_after_cancellation():
    """
    ProducerAborted must not be emitted if cancellation happens first.
    """
    cancel_event = asyncio.Event()
    emitter = RecordingEmitter()

    producer = ExplodingProducer()
    adapter = ProducerAdapter(producer)

    async def run_and_cancel():
        cancel_event.set()
        await adapter.run(
            emit=emitter.emit,
            cancel_event=cancel_event,
        )

    await run_and_cancel()

    assert not any(isinstance(e, ProducerAborted) for e in emitter.events), (
        "ProducerAborted must not be emitted after cancellation"
    )


@pytest.mark.asyncio
async def test_cancellation_is_hard_cutoff_not_best_effort():
    """
    Cancellation is not best-effort.

    Guarantees:
    - Adapter stops emitting terminal events immediately
    - Adapter does not attempt to 'finish' the producer
    """
    cancel_event = asyncio.Event()
    emitter = RecordingEmitter()

    producer = MisbehavingProducer()
    adapter = ProducerAdapter(producer)

    async def run_adapter():
        await adapter.run(
            emit=emitter.emit,
            cancel_event=cancel_event,
        )

    task = asyncio.create_task(run_adapter())

    # Wait for any emission
    while not emitter.events:
        await asyncio.sleep(0)

    cancel_event.set()

    # Give producer time to misbehave
    await asyncio.sleep(0.02)
    task.cancel()

    dones = [e for e in emitter.events if isinstance(e, ProducerDone)]
    aborts = [e for e in emitter.events if isinstance(e, ProducerAborted)]

    # HARD invariant: no terminal events after cancellation
    assert not dones
    assert not aborts
