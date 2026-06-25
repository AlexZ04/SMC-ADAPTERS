import logging
import os
import signal
import threading
import time

from SMK_ADAPTERS.common.monitoring import configureMonitoring
from SMK_ADAPTERS.common.logging_config import configureJsonLogging
from SMK_ADAPTERS.telegram_admin_adapter.settings import loadConfigValues
from SMK_ADAPTERS.vk_adapter.adapter import getStarted, runAdapter
from SMK_ADAPTERS.vk_adapter.settings import loadSettings


LOGGER = logging.getLogger(__name__)


def main() -> None:
    configValues = loadConfigValues()
    logLevelName = os.getenv("LOG_LEVEL") or configValues.get("LOG_LEVEL") or "INFO"
    logLevel = getattr(logging, logLevelName.upper(), logging.INFO)

    configureJsonLogging(logLevel)
    logging.getLogger("pika").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("vk_api").setLevel(logging.WARNING)
    settings = loadSettings()
    configureMonitoring(settings.common.monitoring, f"vk-{settings.vk.adapter_role.lower()}-adapter")

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
