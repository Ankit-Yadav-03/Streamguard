import asyncio
import pytest

from stream_guard.dispatcher import Dispatcher
from stream_guard.chunk_writer import ChunkWriter
from stream_guard.producer import (
    ProducerToken,
    ProducerDone,
    ProducerAborted,
)
from stream_guard.eos_protocol import EOS


# ------------------------------------------------------------
# Test helpers
# ------------------------------------------------------------

class RecordingWriter(ChunkWriter):
    """
    Writer that records writes instead of doing real I/O.
    """
    def __init__(self):
        self.committed = []
        self.eos_written = False
        super().__init__(asyncio.Queue())

    async def write_committed(self, chunks):
        self.committed.extend(chunks)

    async def write_eos(self):
        if self.eos_written:
            raise RuntimeError("EOS written twice")
        self.eos_written = True


async def run_dispatcher_until_done(dispatcher):
    """
    Run dispatcher until it reaches a terminal state.
    """
    await dispatcher.run()


# ------------------------------------------------------------
# FSM Tests
# ------------------------------------------------------------

@pytest.mark.asyncio
async def test_streaming_to_completion_emits_eos_once():
    """
    STREAMING -> FINALIZING -> DRAINING -> COMPLETED
    EOS must be emitted exactly once.
    """
    event_q = asyncio.Queue()
    ack_q = asyncio.Queue()
    cancel_event = asyncio.Event()
    writer = RecordingWriter()

    dispatcher = Dispatcher(
        event_q=event_q,
        writer=writer,
        ack_q=ack_q,
        cancel_event=cancel_event,
        speculative_buffer_limit=1,
        max_inflight_commits=10,
    )

    # Producer emits tokens then completes
    await event_q.put(ProducerToken("a"))
    await event_q.put(ProducerToken("b"))
    await event_q.put(ProducerDone())

    # Consumer ACKs everything
    async def ack_all():
        # Wait until commits happen
        while len(writer.committed) < 2:
            await asyncio.sleep(0)
        await ack_q.put(2)

    await asyncio.gather(
        run_dispatcher_until_done(dispatcher),
        ack_all(),
    )

    assert writer.committed == ["a", "b"]
    assert writer.eos_written is True


@pytest.mark.asyncio
async def test_abort_never_emits_eos():
    """
    STREAMING -> ABORTED
    EOS must NOT be emitted.
    """
    event_q = asyncio.Queue()
    ack_q = asyncio.Queue()
    cancel_event = asyncio.Event()
    writer = RecordingWriter()

    dispatcher = Dispatcher(
        event_q=event_q,
        writer=writer,
        ack_q=ack_q,
        cancel_event=cancel_event,
        speculative_buffer_limit=1,
        max_inflight_commits=10,
    )

    await event_q.put(ProducerToken("a"))
    await event_q.put(ProducerAborted(reason="boom"))

    await run_dispatcher_until_done(dispatcher)

    assert writer.committed == ["a"]
    assert writer.eos_written is False


@pytest.mark.asyncio
async def test_cancellation_aborts_immediately():
    """
    Cancellation event forces ABORTED regardless of producer state.
    """
    event_q = asyncio.Queue()
    ack_q = asyncio.Queue()
    cancel_event = asyncio.Event()
    writer = RecordingWriter()

    dispatcher = Dispatcher(
        event_q=event_q,
        writer=writer,
        ack_q=ack_q,
        cancel_event=cancel_event,
        speculative_buffer_limit=1,
        max_inflight_commits=10,
    )

    # Producer emits a token
    await event_q.put(ProducerToken("a"))

    # Cancel before DONE
    cancel_event.set()

    await run_dispatcher_until_done(dispatcher)

    # Token may or may not be committed depending on timing,
    # but EOS must NEVER be emitted
    assert writer.eos_written is False


@pytest.mark.asyncio
async def test_no_eos_before_consumer_drains():
    """
    EOS must not be emitted until committed == consumed.
    """
    event_q = asyncio.Queue()
    ack_q = asyncio.Queue()
    cancel_event = asyncio.Event()
    writer = RecordingWriter()

    dispatcher = Dispatcher(
        event_q=event_q,
        writer=writer,
        ack_q=ack_q,
        cancel_event=cancel_event,
        speculative_buffer_limit=1,
        max_inflight_commits=10,
    )

    await event_q.put(ProducerToken("a"))
    await event_q.put(ProducerDone())

    async def delayed_ack():
        # Allow dispatcher to commit
        while not writer.committed:
            await asyncio.sleep(0)
        # Delay ACK
        await asyncio.sleep(0.05)
        await ack_q.put(1)

    await asyncio.gather(
        run_dispatcher_until_done(dispatcher),
        delayed_ack(),
    )

    assert writer.committed == ["a"]
    assert writer.eos_written is True


@pytest.mark.asyncio
async def test_accounting_invariant_holds_at_terminal_state():
    """
    produced >= committed >= consumed must always hold.
    """
    event_q = asyncio.Queue()
    ack_q = asyncio.Queue()
    cancel_event = asyncio.Event()
    writer = RecordingWriter()

    dispatcher = Dispatcher(
        event_q=event_q,
        writer=writer,
        ack_q=ack_q,
        cancel_event=cancel_event,
        speculative_buffer_limit=1,
        max_inflight_commits=10,
    )

    await event_q.put(ProducerToken("x"))
    await event_q.put(ProducerToken("y"))
    await event_q.put(ProducerDone())

    async def ack_all():
        while len(writer.committed) < 2:
            await asyncio.sleep(0)
        await ack_q.put(2)

    await asyncio.gather(
        run_dispatcher_until_done(dispatcher),
        ack_all(),
    )

    snapshot = dispatcher.get_accounting_snapshot()

    assert snapshot.produced == 2
    assert snapshot.committed == 2
    assert snapshot.consumed == 2
