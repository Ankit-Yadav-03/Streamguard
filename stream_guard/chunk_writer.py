import asyncio
from stream_guard.eos_protocol import EOS


class ChunkWriter:
    """
    Downstream transport adapter.

    Responsibilities:
    - Write already-committed chunks downstream
    - Deliver EOS exactly once when instructed
    - Never buffer speculative tokens
    - Never apply policy or accounting
    """

    def __init__(
        self,
        committed_q: asyncio.Queue[str],
        *,
        write_delay: float = 0.0,
    ):
        self._committed_q = committed_q
        self._write_delay = write_delay
        self._eos_written = False

    async def write_committed(self, chunks: list[str]) -> None:
        """
        Write a batch of committed chunks downstream.

        Assumes:
        - chunks are already committed by dispatcher
        - ordering is already correct
        """
        for chunk in chunks:
            if self._write_delay:
                await asyncio.sleep(self._write_delay)

            await self._committed_q.put(chunk)

    async def write_eos(self) -> None:
        """
        Write EOS downstream exactly once.
        """
        if self._eos_written:
            raise RuntimeError("EOS already written")

        await self._committed_q.put(EOS)
        self._eos_written = True
