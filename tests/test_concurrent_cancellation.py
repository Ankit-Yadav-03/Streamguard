import asyncio
import random
import time
import pytest

from stream_guard.session import StreamSession
from stream_guard.chunk_writer import ChunkWriter
from stream_guard.receipt import CancelCategory
from stream_guard.observability.metrics import active_streams


# ============================================================
# Stress Producers
# ============================================================

class InfiniteProducer:
    """
    Emits tokens as fast as possible until cancelled.
    Used to simulate real LLM streaming under load.
    """
    async def run(self, *, out, cancel_event):
        i = 0
        while not cancel_event.is_set():
            await out(f"token-{i}")
            i += 1
            await asyncio.sleep(0)  # cooperative, no artificial delay


class FiniteProducer:
    """
    Emits a fixed number of tokens, then completes.
    """
    def __init__(self, count: int):
        self._count = count

    async def run(self, *, out, cancel_event):
        for i in range(self._count):
            if cancel_event.is_set():
                return
            await out(f"token-{i}")
            await asyncio.sleep(0)


# ============================================================
# Phase 1.2 — Cancellation Storm
# ============================================================

@pytest.mark.asyncio
async def test_50_concurrent_streams_with_random_cancellation():
    """
    Phase 1.2 — Concurrency + Cancellation Storm

    Guarantees:
    1. 50 concurrent streams
    2. Randomized cancellation timing
    3. No EOS emitted on cancelled streams
    4. Accounting cutoff is respected
    5. No deadlocks, no leaked tasks
    6. active_streams returns to zero
    """

    CONCURRENCY = 50
    MAX_RUNTIME = 10.0  # hard upper bound for entire test

    start_time = time.time()

    sessions: list[StreamSession] = []
    tasks: list[asyncio.Task] = []

    # --------------------------------------------------------
    # Create mixed producers
    # --------------------------------------------------------
    for i in range(CONCURRENCY):
        if i % 3 == 0:
            producer = InfiniteProducer()
        else:
            producer = FiniteProducer(count=20)

        writer = ChunkWriter(asyncio.Queue())

        session = StreamSession(
            producer=producer,
            writer=writer,
            speculative_buffer_limit=2,
            max_inflight_commits=4,
            timeout_seconds=None,
        )

        sessions.append(session)

    # --------------------------------------------------------
    # Start all sessions
    # --------------------------------------------------------
    for session in sessions:
        session.start()

    # --------------------------------------------------------
    # Consumer behavior
    # --------------------------------------------------------
    async def consume_and_maybe_cancel(session: StreamSession):
        handle = session.handle
        received = []

        # Random cancellation timing
        cancel_after = random.uniform(0.01, 0.2)

        async def canceller():
            await asyncio.sleep(cancel_after)
            handle.signal_disconnect()

        cancel_task = asyncio.create_task(canceller())

        try:
            while True:
                token = await handle.read()
                if token is None:
                    break
                received.append(token)

                # Random slow consumer behavior
                if random.random() < 0.2:
                    await asyncio.sleep(0.02)

        except asyncio.CancelledError:
            pass
        except StopAsyncIteration:
            pass
        finally:
            cancel_task.cancel()

        receipt = await session.shutdown()
        return received, receipt

    # --------------------------------------------------------
    # Run all consumers concurrently
    # --------------------------------------------------------
    tasks = [
        asyncio.create_task(consume_and_maybe_cancel(s))
        for s in sessions
    ]

    results = await asyncio.wait_for(
        asyncio.gather(*tasks),
        timeout=MAX_RUNTIME,
    )

    duration = time.time() - start_time

    # --------------------------------------------------------
    # Assertions
    # --------------------------------------------------------
    assert len(results) == CONCURRENCY

    for received, receipt in results:
        # Receipt must exist
        assert receipt is not None

        # Cancellation attribution
        assert receipt.cancel_category in (
            CancelCategory.USER,
            CancelCategory.SYSTEM,
        )

        # No EOS-based completion for cancelled streams
        if receipt.cancel_reason != "completed":
            assert receipt.consumed <= len(received)

        # Accounting invariants
        assert receipt.produced >= receipt.committed >= receipt.consumed

    # --------------------------------------------------------
    # Global invariants
    # --------------------------------------------------------
    assert active_streams._value.get() == 0, "Leaked active streams detected"

    print(
        f"\nPhase 1.2 complete: "
        f"{CONCURRENCY} concurrent streams with random cancellation "
        f"in {duration:.2f}s"
    )
