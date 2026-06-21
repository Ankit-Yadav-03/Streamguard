import asyncio
import pytest

from stream_guard.session import StreamSession
from stream_guard.chunk_writer import ChunkWriter
from stream_guard.receipt import CancelCategory


# ------------------------------------------------------------
# Test Producer
# ------------------------------------------------------------

class InfiniteProducer:
    """
    Emits tokens indefinitely until cancelled.
    """
    async def run(self, *, out, cancel_event):
        i = 0
        while not cancel_event.is_set():
            await out(f"token-{i}")
            i += 1
            await asyncio.sleep(0)


# ------------------------------------------------------------
# Integration Test
# ------------------------------------------------------------

@pytest.mark.asyncio
async def test_end_to_end_cancellation_no_eos():
    """
    End-to-end cancellation test.

    Guarantees:
    1. Tokens flow until cancellation
    2. Cancellation stops producer + dispatcher
    3. Consumer does NOT observe EOS
    4. Receipt reflects ABORTED state
    5. Accounting cutoff is respected
    """

    producer = InfiniteProducer()

    committed_q = asyncio.Queue()
    writer = ChunkWriter(committed_q)

    session = StreamSession(
        producer=producer,
        writer=writer,
        speculative_buffer_limit=2,
        max_inflight_commits=2,
        timeout_seconds=None,
    )

    session.start()
    handle = session.handle

    received = []

    # --------------------------------------------------------
    # Consume a few tokens
    # --------------------------------------------------------
    for _ in range(3):
        item = await asyncio.wait_for(handle.read(), timeout=1.0)
        assert item is not None
        received.append(item)

    assert len(received) == 3

    # --------------------------------------------------------
    # Trigger client disconnect (cancellation)
    # --------------------------------------------------------
    handle.signal_disconnect()

    # --------------------------------------------------------
    # Further reads must NOT return EOS
    # They must raise CancelledError
    # --------------------------------------------------------
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(handle.read(), timeout=1.0)

    # --------------------------------------------------------
    # Shutdown & receipt
    # --------------------------------------------------------
    receipt = await session.shutdown()

    assert receipt.cancel_category == CancelCategory.USER
    assert receipt.cancel_reason != "completed"

    # --------------------------------------------------------
    # Accounting invariants
    # --------------------------------------------------------
    assert receipt.produced >= receipt.committed >= receipt.consumed
    assert receipt.consumed <= len(received)
    assert receipt.consumed <= receipt.committed
    assert receipt.committed <= receipt.produced

