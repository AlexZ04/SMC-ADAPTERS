import logging
import os
import signal
import threading
import time

from SMK_ADAPTERS.telegram_admin_adapter.settings import loadConfigValues
from SMK_ADAPTERS.vk_adapter.adapter import getStarted, runAdapter


LOGGER = logging.getLogger(__name__)


def main() -> None:
    configValues = loadConfigValues()
    logLevelName = os.getenv("LOG_LEVEL") or configValues.get("LOG_LEVEL") or "INFO"
    logLevel = getattr(logging, logLevelName.upper(), logging.INFO)

    logging.basicConfig(
        level=logLevel,
        format="%(asctime)s %(levelname)s [%(threadName)s] %(name)s: %(message)s",
    )
    logging.getLogger("pika").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("vk_api").setLevel(logging.WARNING)

    stopEvent = threading.Event()

    def stop(signum: int, frame: object) -> None:
        LOGGER.info("Получен сигнал остановки: %s", signum)
        stopEvent.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    getStarted()

    runner = threading.Thread(target=runAdapter, name="vk-adapter", daemon=True)
    runner.start()

    while not stopEvent.is_set() and runner.is_alive():
        time.sleep(1)


if __name__ == "__main__":
    main()
