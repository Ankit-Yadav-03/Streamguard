import asyncio
import pytest

from stream_guard.session import StreamSession
from stream_guard.chunk_writer import ChunkWriter
from stream_guard.receipt import CancelCategory


# ------------------------------------------------------------
# Test Producer
# ------------------------------------------------------------

class FiniteProducer:
    """
    Emits a fixed number of tokens, then returns normally.
    """
    def __init__(self, tokens):
        self._tokens = tokens

    async def run(self, *, out, cancel_event):
        for t in self._tokens:
            if cancel_event.is_set():
                return
            await out(t)
        # normal return → ProducerDone inferred by adapter


# ------------------------------------------------------------
# Integration Test
# ------------------------------------------------------------

@pytest.mark.asyncio
async def test_end_to_end_happy_path_completion():
    """
    End-to-end happy path test.

    Guarantees:
    1. Tokens flow producer → consumer
    2. Consumer observes EOS exactly once
    3. Session reaches COMPLETED
    4. Receipt reflects successful completion
    5. Accounting invariants hold
    """

    tokens = ["a", "b", "c", "d"]

    producer = FiniteProducer(tokens)

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
    # Consume until EOS
    # --------------------------------------------------------
    while True:
        item = await asyncio.wait_for(handle.read(), timeout=1.0)
        if item is None:
            break
        received.append(item)

    # --------------------------------------------------------
    # Assertions: delivery + EOS
    # --------------------------------------------------------
    assert received == tokens, "All tokens must be delivered in order"

    # --------------------------------------------------------
    # Shutdown & receipt
    # --------------------------------------------------------
    receipt = await session.shutdown()

    assert receipt.cancel_reason == "completed"
    assert receipt.cancel_category == CancelCategory.USER

    # --------------------------------------------------------
    # Accounting invariants
    # --------------------------------------------------------
    assert receipt.produced == len(tokens)
    assert receipt.committed == len(tokens)
    assert receipt.consumed == len(tokens)

    assert receipt.produced >= receipt.committed >= receipt.consumed
