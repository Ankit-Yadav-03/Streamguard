import asyncio
from typing import Protocol, Union
from dataclasses import dataclass
from enum import Enum, auto



class ClientProducer(Protocol):
    """
    Client-facing streaming producer contract.

    Clients MUST:
    - emit raw tokens via `out(token: str)`
    - stop promptly when cancel_event is set
    - return normally on clean completion
    - NOT emit EOS
    - NOT do accounting
    """

    async def run(
        self,
        *,
        out,                
        cancel_event: asyncio.Event,
    ) -> None:
        ...


class ProducerEventType(Enum):
    TOKEN = auto()
    DONE = auto()
    ABORTED = auto()


@dataclass(frozen=True)
class ProducerToken():
    value: str


@dataclass(frozen=True)
class ProducerDone:
    pass


@dataclass(frozen=True)
class ProducerAborted:
    reason: str


ProducerEvent = Union[
    ProducerToken,
    ProducerDone,
    ProducerAborted,
]


class ProducerAdapter:
    """
    Wraps a client producer and enforces protocol semantics.

    Guarantees:
    - Hard cancellation cutoff
    - No events after cancel
    - DONE only if not cancelled
    - ABORT only if not cancelled
    """

    def __init__(self, producer):
        self._producer = producer

    async def run(self, *, emit, cancel_event):
        cancelled = False

        async def guarded_emit(event: ProducerEvent):
            nonlocal cancelled
            if cancel_event.is_set():
                cancelled = True
                return
            await emit(event)

        async def out(token: str):
            if cancel_event.is_set():
                return
            await guarded_emit(ProducerToken(token))

        try:
            await self._producer.run(
                out=out,
                cancel_event=cancel_event,
            )

            if not cancel_event.is_set() and not cancelled:
                await guarded_emit(ProducerDone())

        except Exception as e:
            if not cancel_event.is_set() and not cancelled:
                await guarded_emit(ProducerAborted(reason=str(e)))


class SampleProducer:
    """
    Simple demo producer.

    Emits numbered tokens until cancelled.
    """

    async def run(
        self,
        *,
        out,
        cancel_event: asyncio.Event,
    ) -> None:
        i = 0
        while not cancel_event.is_set():
            await out(f"token-{i}")
            i += 1
            await asyncio.sleep(0.01)
