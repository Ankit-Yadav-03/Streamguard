import asyncio
from enum import Enum, auto
from dataclasses import dataclass

from stream_guard.producer import (
    ProducerEvent,
    ProducerToken,
    ProducerDone,
    ProducerAborted,
)
from stream_guard.chunk_writer import ChunkWriter
from stream_guard.observability.metrics import (
    tokens_committed,
    tokens_consumed,
) 


# ============================================================
# Dispatcher FSM States
# ============================================================

class DispatcherState(Enum):
    INIT = auto()
    STREAMING = auto()
    FINALIZING = auto()
    DRAINING = auto()
    COMPLETING = auto()
    COMPLETED = auto()
    ABORTED = auto()


# ============================================================
# Accounting (AUTHORITATIVE)
# ============================================================

@dataclass(frozen=True)
class AccountingSnapshot:
    produced: int
    committed: int
    consumed: int


@dataclass
class _Accounting:
    produced: int = 0
    committed: int = 0
    consumed: int = 0


# ============================================================
# Dispatcher
# ============================================================

class Dispatcher:
    """
    Protocol-authoritative dispatcher with accounting hooks.
    """

    def __init__(
        self,
        *,
        event_q: asyncio.Queue[ProducerEvent],
        writer: ChunkWriter,
        ack_q: asyncio.Queue[int],
        cancel_event: asyncio.Event,
        speculative_buffer_limit: int,
        max_inflight_commits: int,
    ):
        self._state = DispatcherState.INIT
        self._event_q = event_q
        self._writer = writer
        self._ack_q = ack_q
        self._cancel_event = cancel_event

        self._buffer: list[str] = []
        self._unread_committed = 0

        self._spec_limit = speculative_buffer_limit
        self._max_inflight = max_inflight_commits

        self._accounting = _Accounting()
        self._eos_emitted = False


    # ========================================================
    # Public Entry
    # ========================================================

    async def run(self) -> None:
        self._enter(DispatcherState.STREAMING)

        while self._state not in (
            DispatcherState.COMPLETED,
            DispatcherState.ABORTED,
        ):
            if self._cancel_event.is_set():
                self._enter(DispatcherState.ABORTED)
                break

            if self._state == DispatcherState.STREAMING:
                await self._streaming_step()

            elif self._state == DispatcherState.FINALIZING:
                await self._finalize()
                self._enter(DispatcherState.DRAINING)

            elif self._state == DispatcherState.DRAINING:
                await self._drain_step()

            elif self._state == DispatcherState.COMPLETING:
                await self._emit_eos()
                self._enter(DispatcherState.COMPLETED)

            else:
                raise RuntimeError(f"Invalid dispatcher state {self._state}")

        self._assert_invariants()


    # ========================================================
    # FSM Steps
    # ========================================================

    async def _streaming_step(self) -> None:
        await self._apply_acks(non_blocking=True)

        event = await self._event_q.get()
        self._event_q.task_done()

        if isinstance(event, ProducerToken):
            self._on_token(event)

        elif isinstance(event, ProducerDone):
            self._enter(DispatcherState.FINALIZING)

        elif isinstance(event, ProducerAborted):
            self._cancel_event.set()
            self._enter(DispatcherState.ABORTED)

        else:
            raise RuntimeError(f"Unknown producer event {event}")

        await self._maybe_commit_streaming()


    async def _finalize(self) -> None:
        if self._buffer:
            await self._commit(len(self._buffer))


    async def _drain_step(self) -> None:
        await self._apply_acks(non_blocking=False)

        if self._accounting.consumed == self._accounting.committed:
            self._enter(DispatcherState.COMPLETING)


    # ========================================================
    # Token / Commit Logic
    # ========================================================

    def _on_token(self, event: ProducerToken) -> None:
        self._accounting.produced += 1
        self._buffer.append(event.value)


    async def _maybe_commit_streaming(self) -> None:
        if (
            len(self._buffer) >= self._spec_limit
            and self._unread_committed < self._max_inflight
        ):
            to_commit = min(
                len(self._buffer),
                self._max_inflight - self._unread_committed,
            )
            await self._commit(to_commit)


    async def _commit(self, n: int) -> None:
        chunks = self._buffer[:n]
        del self._buffer[:n]

        await self._writer.write_committed(chunks)

        self._accounting.committed += n
        self._unread_committed += n

        tokens_committed.inc(n)

    async def _apply_acks(self, *, non_blocking: bool) -> None:
        if non_blocking:
            while not self._ack_q.empty():
                n = self._ack_q.get_nowait()
                self._ack_q.task_done()
                self._on_consume(n)
        else:
            n = await self._ack_q.get()
            self._ack_q.task_done()
            self._on_consume(n)


    def _on_consume(self, n: int) -> None:
        self._accounting.consumed += n
        self._unread_committed -= n
        if self._unread_committed < 0:
            raise RuntimeError("Consumed more than committed")

        tokens_consumed.inc()

    # ========================================================
    # EOS
    # ========================================================

    async def _emit_eos(self) -> None:
        if self._eos_emitted:
            raise RuntimeError("EOS already emitted")

        await self._writer.write_eos()
        self._eos_emitted = True


    # ========================================================
    # Accounting Hook (READ-ONLY)
    # ========================================================

    def get_accounting_snapshot(self) -> AccountingSnapshot:
        """
        Returns an immutable snapshot of accounting state.
        Safe to call only after terminal state.
        """
        return AccountingSnapshot(
            produced=self._accounting.produced,
            committed=self._accounting.committed,
            consumed=self._accounting.consumed,
        )


    # ========================================================
    # FSM
    # ========================================================

    def _enter(self, new_state: DispatcherState) -> None:
        self._validate_transition(self._state, new_state)
        self._state = new_state


    def _validate_transition(self, old: DispatcherState, new: DispatcherState) -> None:
        legal = {
            DispatcherState.INIT: {DispatcherState.STREAMING},
            DispatcherState.STREAMING: {
                DispatcherState.FINALIZING,
                DispatcherState.ABORTED,
            },
            DispatcherState.FINALIZING: {
                DispatcherState.DRAINING,
                DispatcherState.ABORTED,
            },
            DispatcherState.DRAINING: {
                DispatcherState.COMPLETING,
                DispatcherState.ABORTED,
            },
            DispatcherState.COMPLETING: {DispatcherState.COMPLETED},
        }

        if old in legal and new in legal[old]:
            return

        if old in (DispatcherState.COMPLETED, DispatcherState.ABORTED):
            raise RuntimeError(f"Illegal transition from terminal state {old}")

        raise RuntimeError(f"Illegal transition {old} → {new}")


    # ========================================================
    # Invariants
    # ========================================================

    def _assert_invariants(self) -> None:
        a = self._accounting
        if not (a.produced >= a.committed >= a.consumed):
            raise RuntimeError(f"Accounting invariant violated: {a}")
