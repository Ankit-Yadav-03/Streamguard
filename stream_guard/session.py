import asyncio
import time
import uuid
from enum import Enum, auto
from typing import Optional

from stream_guard.chunk_writer import ChunkWriter
from stream_guard.producer import ClientProducer, ProducerAdapter
from stream_guard.dispatcher import Dispatcher
from stream_guard.handle import (
    StreamHandle,
    ConsumerEOSObserved,
    ConsumerCancelled,
)
from stream_guard.receipt import StreamReceipt, CancelCategory
from stream_guard.observability.metrics import (
    streams_aborted,
    streams_started,
    active_streams,
)

class TerminalState(Enum):
    RUNNING = auto()
    COMPLETED = auto()
    ABORTED = auto()



class StreamSession:
    """
    Session rebuilt around terminal protocol states
    with authoritative accounting.
    """

    def __init__(
        self,
        *,
        producer: ClientProducer,
        writer: ChunkWriter,
        speculative_buffer_limit: int,
        max_inflight_commits: int,
        timeout_seconds: Optional[float] = None,
    ):
        self.stream_id = uuid.uuid4().hex

        self._state = TerminalState.RUNNING
        self._started_at = time.time()
        self._finalized_at: Optional[float] = None

        self._cancel_event = asyncio.Event()
        self._cancel_reason: Optional[str] = None
        self._cancel_category: Optional[CancelCategory] = None
        self._accounting_cutoff_at: Optional[float] = None

        self._producer_event_q = asyncio.Queue()
        self._ack_q = asyncio.Queue()
        self._consumer_event_q = asyncio.Queue()

        self._producer_adapter = ProducerAdapter(producer)

        self._dispatcher = Dispatcher(
            event_q=self._producer_event_q,
            writer=writer,
            ack_q=self._ack_q,
            cancel_event=self._cancel_event,
            speculative_buffer_limit=speculative_buffer_limit,
            max_inflight_commits=max_inflight_commits,
        )

        self.handle = StreamHandle(
            stream_id=self.stream_id,
            committed_q=writer._committed_q,
            ack_q=self._ack_q,
            consumer_event_q=self._consumer_event_q,
            cancel_event=self._cancel_event,
        )

        self._producer_task = None
        self._dispatcher_task = None
        self._consumer_watch_task = None
        self._timeout_task = None

        self._timeout_seconds = timeout_seconds
        self._receipt: Optional[StreamReceipt] = None


    def start(self) -> None:
        streams_started.inc()
        active_streams.inc()

        self._producer_task = asyncio.create_task(self._run_producer())
        self._dispatcher_task = asyncio.create_task(self._dispatcher.run())
        self._consumer_watch_task = asyncio.create_task(
            self._watch_consumer_events()
        )

        if self._timeout_seconds is not None:
            self._timeout_task = asyncio.create_task(self._timeout_watchdog())


    async def _run_producer(self) -> None:
        async def emit(event):
            await self._producer_event_q.put(event)

        await self._producer_adapter.run(
            emit=emit,
            cancel_event=self._cancel_event,
        )
        

    async def _watch_consumer_events(self) -> None:
        while self._state is TerminalState.RUNNING:
            event = await self._consumer_event_q.get()
            self._consumer_event_q.task_done()

            if isinstance(event, ConsumerEOSObserved):
                self._complete()
                return

            if isinstance(event, ConsumerCancelled):
                self._abort(
                    reason=event.reason,
                    category=CancelCategory.USER,
                )
                return


    async def _timeout_watchdog(self) -> None:
        try:
            await asyncio.sleep(self._timeout_seconds)
            self._abort(
                reason="timeout",
                category=CancelCategory.SYSTEM,
            )
        except asyncio.CancelledError:
            return


    def _complete(self) -> None:
        if self._state is not TerminalState.RUNNING:
            return

        self._state = TerminalState.COMPLETED
        active_streams.dec()
        asyncio.create_task(self._finalize_receipt())


    def _abort(self, *, reason: str, category: CancelCategory) -> None:
        streams_aborted.labels(category=category.value).inc()
        active_streams.dec()

        if self._state is not TerminalState.RUNNING:
            return

        self._state = TerminalState.ABORTED
        self._cancel_reason = reason
        self._cancel_category = category
        self._accounting_cutoff_at = time.time()
        self._cancel_event.set()

        asyncio.create_task(self._finalize_receipt())


    def cancel(self, *, reason: str, category: CancelCategory) -> None:
        self._abort(reason=reason, category=category)


    async def _finalize_receipt(self) -> None:
        if self._receipt is not None:
            return

        self._finalized_at = time.time()

        snapshot = self._dispatcher.get_accounting_snapshot()

        estimated_prevented = max(
            0,
            snapshot.produced - snapshot.committed,
        )

        self._receipt = StreamReceipt(
            stream_id=self.stream_id,
            cancel_reason=self._cancel_reason or "completed",
            cancel_category=self._cancel_category or CancelCategory.USER,
            started_at=self._started_at,
            cancel_requested_at=self._accounting_cutoff_at,
            accounting_cutoff_at=self._accounting_cutoff_at,
            finalized_at=self._finalized_at,
            produced=snapshot.produced,
            committed=snapshot.committed,
            consumed=snapshot.consumed,
            estimated_prevented=estimated_prevented,
        )


    async def wait_for_terminal(self):
        while self._receipt is None:
            await asyncio.sleep(0)
        return self._receipt


    async def shutdown(self) -> StreamReceipt:
        """
        Authoritative termination.

        - Allows protocol terminal events (EOS / USER cancel) to win
        - Forces SYSTEM abort only if nothing else terminated the session
        - Never blocks
        """

        await asyncio.sleep(0)

        if self._state is TerminalState.RUNNING:
            self._abort(
                reason="shutdown",
                category=CancelCategory.SYSTEM,
            )

        for task in (
            self._producer_task,
            self._dispatcher_task,
            self._consumer_watch_task,
            self._timeout_task,
        ):
            if task:
                task.cancel()

        if self._receipt is None:
            await self._finalize_receipt()

        return self._receipt

