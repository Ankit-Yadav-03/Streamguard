import asyncio


async def cancellable_get(*, queue: asyncio.Queue, cancel_event: asyncio.Event):
    """
    Await one item from queue OR cancellation, whichever happens first.

    Semantics:
    - If cancellation wins, the queued item (if any) is intentionally dropped.
    - This is FAIL-CLOSED by design to prevent post-cancel spend.
    - Raises asyncio.CancelledError on cancellation.
    """
    get_task = asyncio.create_task(queue.get())
    cancel_task = asyncio.create_task(cancel_event.wait())

    try:
        done, _ = await asyncio.wait(
            {get_task, cancel_task},
            return_when=asyncio.FIRST_COMPLETED,
        )

        if cancel_task in done:
            raise asyncio.CancelledError("Cancelled while waiting for queue item")

        return get_task.result()

    finally:
        for task in (get_task, cancel_task):
            if not task.done():
                task.cancel()