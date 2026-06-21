import asyncio
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

from stream_guard.eos_protocol import EOS


# ============================================================
# Consumer Completion Events (INTERNAL)
# ============================================================

class ConsumerEventType(Enum):
    CONSUMED = auto()
    EOS_OBSERVED = auto()
    CANCELLED = auto()


@dataclass(frozen=True)
class ConsumerConsumed:
    count: int


@dataclass(frozen=True)
class ConsumerEOSObserved:
    pass


@dataclass(frozen=True)
class ConsumerCancelled:
    reason: str


ConsumerEvent = (
    ConsumerConsumed
    | ConsumerEOSObserved
    | ConsumerCancelled
)


# ============================================================
# Stream Handle (Consumer Adapter)
# ============================================================

class StreamHandle:
    """
    Consumer-facing stream handle.

    Responsibilities:
    - Deliver committed tokens to the client
    - ACK token delivery explicitly
    - Observe EOS exactly once
    - Report completion to the session/dispatcher
    - Never infer completion
    """

    def __init__(
        self,
        *,
        stream_id: str,
        committed_q: asyncio.Queue[str],
        ack_q: asyncio.Queue[int],
        consumer_event_q: asyncio.Queue[ConsumerEvent],
        cancel_event: asyncio.Event,
    ):
        self.stream_id = stream_id
        self._committed_q = committed_q
        self._ack_q = ack_q
        self._consumer_event_q = consumer_event_q
        self._cancel_event = cancel_event

        self._eos_seen = False


    # ========================================================
    # Public API
    # ========================================================

    async def read(self) -> Optional[str]:
        """
        Read the next token.

        Returns:
        - str token on normal delivery
        - None on clean end-of-stream (EOS observed)

        Raises:
        - asyncio.CancelledError if cancelled before EOS
        """

        # Cancellation before EOS is NOT completion
        if self._cancel_event.is_set() and not self._eos_seen:
            await self._consumer_event_q.put(
                ConsumerCancelled(reason="cancelled_before_eos")
            )
            raise asyncio.CancelledError("Stream cancelled")

        item = await self._committed_q.get()
        self._committed_q.task_done()

        # ----------------------------------------------------
        # EOS PATH (STRUCTURALLY NON-ACKABLE)
        # ----------------------------------------------------
        if item is EOS:
            if self._eos_seen:
                raise RuntimeError("EOS observed more than once")

            self._eos_seen = True

            await self._consumer_event_q.put(
                ConsumerEOSObserved()
            )

            # EOS is NOT ACKed
            return None

        # ----------------------------------------------------
        # TOKEN PATH
        # ----------------------------------------------------
        await self._ack_q.put(1)

        await self._consumer_event_q.put(
            ConsumerConsumed(count=1)
        )

        return item


    def signal_disconnect(self) -> None:
        """
        Client disconnect intent.

        This does NOT complete the stream.
        It only triggers cancellation.
        """
        if not self._cancel_event.is_set():
            self._cancel_event.set()
