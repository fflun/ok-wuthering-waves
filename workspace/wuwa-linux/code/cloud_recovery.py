"""Bounded retries for observations only; actions are never replayed."""
import asyncio


class TransientFrameError(RuntimeError):
    pass


async def recover_frame(read, release, recovered, pause=asyncio.sleep, attempts=3):
    for attempt in range(attempts):
        try:
            frame = await read()
            if attempt:
                # Require another valid observation before resuming inputs.
                frame = await read()
                recovered(attempt)
            return frame
        except (TransientFrameError, TimeoutError, ConnectionError):
            await release()
            if attempt == attempts-1:
                raise
            await pause(.4)
