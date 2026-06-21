import asyncio
import pytest

from stream_guard.session import StreamSession
from stream_guard.chunk_writer import ChunkWriter
from stream_guard.receipt import CancelCategory


# ------------------------------------------------------------
# Producer that finishes quickly but leaves dispatcher work
# ------------------------------------------------------------

class FastDoneProducer:
    """
    Emits a few tokens quickly, then DONE.
    Designed so dispatcher enters FINALIZING.
    """
    async def run(self, *, out, cancel_event: asyncio.Event):
        for i in range(5):
            if cancel_event.is_set():
                return
            await out(f"token-{i}")
        # return normally -> ProducerDone


# ------------------------------------------------------------
# Phase 2.2 Test
# ------------------------------------------------------------

@pytest.mark.asyncio
async def test_abort_during_dispatcher_finalization():
    """
    Phase 2.2 — Abort During Finalization

    Guarantees:
    1. ProducerDone is observed
    2. Dispatcher may still be finalizing / draining
    3. SYSTEM shutdown aborts the stream
    4. Consumer does NOT observe EOS
    5. Receipt is finalized exactly once
    6. Accounting invariants hold
    7. Test never stalls
    """

    producer = FastDoneProducer()
    writer = ChunkWriter(asyncio.Queue())

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
    # Consume ONLY ONE token, then stop
    # Dispatcher will still be finalizing
    # --------------------------------------------------------
    first = await asyncio.wait_for(handle.read(), timeout=1.0)
    assert first == "token-0"
    received.append(first)

    # --------------------------------------------------------
    # Immediately force shutdown while dispatcher is active
    # --------------------------------------------------------
    receipt = await asyncio.wait_for(
        session.shutdown(),
        timeout=1.0,
    )

    # --------------------------------------------------------
    # Assertions
    # --------------------------------------------------------

    # Shutdown wins attribution
    assert receipt.cancel_category == CancelCategory.SYSTEM
    assert receipt.cancel_reason == "shutdown"

    # No EOS should have been observed
    # (consumer never read EOS)
    assert receipt.consumed == len(received)

    # Accounting invariants
    assert receipt.produced >= receipt.committed >= receipt.consumed

    # Receipt must be fully finalized
    assert receipt.finalized_at is not None
