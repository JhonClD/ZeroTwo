"""Cola FIFO para serializar descargas de archivos."""

import asyncio
from collections import deque
from dataclasses import dataclass
from typing import Awaitable, Callable, Deque, Generic, Optional, TypeVar


T = TypeVar("T")


@dataclass
class _QueueItem(Generic[T]):
    label: str
    job: Callable[[], Awaitable[T]]
    future: asyncio.Future


class DownloadQueue:
    """Ejecuta una sola descarga a la vez, respetando el orden de llegada."""

    def __init__(self):
        self._items: Deque[_QueueItem] = deque()
        self._worker_task: Optional[asyncio.Task] = None
        self._active = False

    @property
    def pending(self) -> int:
        """Cantidad de descargas esperando, sin contar la activa."""
        return len(self._items)

    @property
    def active(self) -> bool:
        return self._active

    async def run(
        self,
        label: str,
        job: Callable[[], Awaitable[T]],
        on_queued: Optional[Callable[[int], Awaitable[None]]] = None,
    ) -> T:
        """Añade ``job`` a la cola y devuelve su resultado cuando termine."""
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        position = len(self._items) + (1 if self._active else 0) + 1
        self._items.append(_QueueItem(label, job, future))

        if position > 1 and on_queued:
            try:
                await on_queued(position)
            except Exception:
                pass

        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker())
        return await future

    async def _worker(self):
        while self._items:
            item = self._items.popleft()
            self._active = True
            try:
                result = await item.job()
            except asyncio.CancelledError:
                if not item.future.done():
                    item.future.cancel()
                raise
            except Exception as error:
                if not item.future.done():
                    item.future.set_exception(error)
            else:
                if not item.future.done():
                    item.future.set_result(result)
            finally:
                self._active = False


# Una única cola para los handlers de URL y Google Drive.
download_queue = DownloadQueue()
