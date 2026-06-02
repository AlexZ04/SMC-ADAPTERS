import asyncio
import threading
from collections.abc import Coroutine
from typing import Any


class TelegramAsyncRuntime:
    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.runLoop, name="telegram-admin-async-loop", daemon=True)

    def start(self) -> None:
        if self.thread.is_alive():
            return

        self.thread.start()

    def runLoop(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def run(self, coroutine: Coroutine[Any, Any, Any]) -> Any:
        self.start()
        future = asyncio.run_coroutine_threadsafe(coroutine, self.loop)
        return future.result()
