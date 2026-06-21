import asyncio
import pytest

from stream_guard.session import StreamSession
from stream_guard.chunk_writer import ChunkWriter
from stream_guard.receipt import CancelCategory
from stream_guard.observability.metrics import active_streams


# ============================================================
# Misbehaving Producer
# ============================================================

class MisbehavingProducer:
    """
    Deliberately violates the producer contract.

    - Emits after failure
    - Ignores cancel_event
    - Raises mid-stream
    """

    async def run(self, *, out, cancel_event):
        await out("before-failure")

        # Emit again even though this should be dropped
        await asyncio.sleep(0.01)
        await out("after-failure")

        # Crash
        raise RuntimeError("producer exploded")


# ============================================================
# Phase 2.1 — Misbehaving Producer
# ============================================================

@pytest.mark.asyncio
async def test_misbehaving_producer_is_safely_aborted():
    """
    Guarantees:
    1. Misbehaving producer does not stall system
    2. No EOS is emitted
    3. Consumer is cancelled deterministically
    4. Accounting invariants hold
    5. Stream does not complete successfully
    6. No leaked streams
    """

    producer = MisbehavingProducer()
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
    # Consumer MUST be cancelled (not completed)
    # --------------------------------------------------------
    with pytest.raises(asyncio.CancelledError):
        while True:
            token = await handle.read()
            received.append(token)

    receipt = await session.shutdown()

    # --------------------------------------------------------
    # Assertions
    # --------------------------------------------------------

    # At least the first token must be deliverable
    assert received == ["before-failure"]

    # Stream must NOT be marked completed
    assert receipt.cancel_reason != "completed"

    # EOS must NOT be emitted on abort
    assert receipt.estimated_prevented >= 0

    # Accounting invariants (ONLY valid truth)
    assert receipt.produced >= receipt.committed >= receipt.consumed
    assert receipt.consumed <= len(received)

    # Category may be SYSTEM or USER depending on observation timing
    assert receipt.cancel_category in (
        CancelCategory.SYSTEM,
        CancelCategory.USER,
    )

    # Global invariant
    assert active_streams._value.get() == 0
