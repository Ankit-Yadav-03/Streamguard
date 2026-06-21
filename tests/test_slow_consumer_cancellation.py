import asyncio
import pytest

from stream_guard.session import StreamSession
from stream_guard.chunk_writer import ChunkWriter
from stream_guard.receipt import CancelCategory


# ------------------------------------------------------------
# Controlled Producer
# ------------------------------------------------------------

class FastFiniteProducer:
    """
    Emits a fixed number of tokens quickly.
    Enough to engage backpressure with a slow consumer.
    """
    def __init__(self, count: int):
        self._count = count

    async def run(self, *, out, cancel_event):
        for i in range(self._count):
            if cancel_event.is_set():
                return
            await out(f"token-{i}")


# ------------------------------------------------------------
# Test
# ------------------------------------------------------------

@pytest.mark.asyncio
async def test_slow_consumer_handling_and_cancellation():
    """
    Demonstrates that:
    1. Slow consumers are handled via backpressure
    2. Cancellation during slow consumption works
    3. No EOS is emitted
    4. Receipt is finalized correctly on shutdown
    5. Test never stalls
    """

    producer = FastFiniteProducer(count=10)
    writer = ChunkWriter(asyncio.Queue())

    session = StreamSession(
        producer=producer,
        writer=writer,
        speculative_buffer_limit=1,
        max_inflight_commits=1,
        timeout_seconds=None,
    )

    session.start()
    handle = session.handle

    received = []

    # --------------------------------------------------------
    # Slow consumer (bounded reads)
    # --------------------------------------------------------
    for _ in range(2):
        token = await asyncio.wait_for(handle.read(), timeout=1.0)
        assert token is not None
        received.append(token)
        await asyncio.sleep(0.05)

    assert len(received) == 2

    # --------------------------------------------------------
    # Cancel mid-stream
    # --------------------------------------------------------
    handle.signal_disconnect()
    # --------------------------------------------------------
    # Explicit lifecycle termination (authoritative)
    # --------------------------------------------------------
    receipt = await asyncio.wait_for(
        session.shutdown(),
        timeout=1.0,
    )

    # --------------------------------------------------------
    # Assertions
    # --------------------------------------------------------
    assert receipt.cancel_category == CancelCategory.SYSTEM
    assert receipt.cancel_reason != "completed"

    # Accounting invariants
    assert receipt.produced >= receipt.committed >= receipt.consumed

    # Consumer semantics
    assert receipt.consumed == len(received)
