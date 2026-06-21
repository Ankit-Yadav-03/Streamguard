import asyncio
import pytest
import time

from stream_guard.session import StreamSession
from stream_guard.chunk_writer import ChunkWriter
from stream_guard.receipt import CancelCategory
from stream_guard.observability.metrics import active_streams


# ============================================================
# Finite Producer (well-behaved)
# ============================================================

class FiniteProducer:
    def __init__(self, count: int):
        self._count = count

    async def run(self, *, out, cancel_event):
        for i in range(self._count):
            if cancel_event.is_set():
                return
            await out(f"token-{i}")
            await asyncio.sleep(0)  # yield, no artificial slowdown


# ============================================================
# Phase 1.1 — Concurrent Normal Streams
# ============================================================

@pytest.mark.asyncio
async def test_50_concurrent_streams_happy_path():
    """
    Phase 1.1 — Baseline concurrency test

    Guarantees:
    1. 50 streams run concurrently
    2. No head-of-line blocking
    3. All streams complete successfully
    4. Accounting invariants hold per stream
    5. No leaked active streams
    """

    CONCURRENCY = 50
    TOKENS_PER_STREAM = 200

    start_time = time.time()

    sessions: list[StreamSession] = []
    tasks: list[asyncio.Task] = []

    # --------------------------------------------------------
    # Create sessions
    # --------------------------------------------------------
    for _ in range(CONCURRENCY):
        producer = FiniteProducer(TOKENS_PER_STREAM)
        writer = ChunkWriter(asyncio.Queue())

        session = StreamSession(
            producer=producer,
            writer=writer,
            speculative_buffer_limit=4,
            max_inflight_commits=8,
            timeout_seconds=None,
        )

        sessions.append(session)

    # --------------------------------------------------------
    # Start all sessions concurrently
    # --------------------------------------------------------
    for session in sessions:
        session.start()

    # --------------------------------------------------------
    # Consume all streams concurrently
    # --------------------------------------------------------
    async def consume(session: StreamSession):
        handle = session.handle
        received = []

        while True:
            try:
                token = await handle.read()
                if token is None:
                    break
                received.append(token)
            except StopAsyncIteration:
                break

        receipt = await session.shutdown()
        return received, receipt

    tasks = [asyncio.create_task(consume(s)) for s in sessions]

    results = await asyncio.gather(*tasks)

    duration = time.time() - start_time

    # --------------------------------------------------------
    # Assertions
    # --------------------------------------------------------
    assert len(results) == CONCURRENCY

    for received, receipt in results:
        # Delivery
        assert len(received) == TOKENS_PER_STREAM

        # Receipt correctness
        assert receipt.cancel_reason == "completed"
        assert receipt.cancel_category == CancelCategory.USER

        # Accounting invariants
        assert receipt.produced >= receipt.committed >= receipt.consumed
        assert receipt.consumed == TOKENS_PER_STREAM
        assert receipt.estimated_prevented == 0

    # --------------------------------------------------------
    # Global invariants
    # --------------------------------------------------------
    assert active_streams._value.get() == 0, "Leaked active streams detected"

    print(
        f"\nPhase 1.1 complete: "
        f"{CONCURRENCY} streams × {TOKENS_PER_STREAM} tokens "
        f"in {duration:.2f}s"
    )
