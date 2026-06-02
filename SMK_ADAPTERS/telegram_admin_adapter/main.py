import logging
import signal
import threading
import time
import os

from SMK_ADAPTERS.telegram_admin_adapter.adapter import getStarted, runAdapter
from SMK_ADAPTERS.telegram_admin_adapter.settings import loadConfigValues


LOGGER = logging.getLogger(__name__)


def main() -> None:
    config_values = loadConfigValues()
    log_level_name = os.getenv("LOG_LEVEL") or config_values.get("LOG_LEVEL") or "INFO"
    log_level = getattr(logging, log_level_name.upper(), logging.INFO)

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s [%(threadName)s] %(name)s: %(message)s",
    )
    logging.getLogger("pika").setLevel(logging.WARNING)

    stop_event = threading.Event()

    def stop(signum: int, frame: object) -> None:
        LOGGER.info("Получен сигнал остановки: %s", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    getStarted()

    runner = threading.Thread(target=runAdapter, name="telegram-admin-adapter", daemon=True)
    runner.start()

    while not stop_event.is_set() and runner.is_alive():
        time.sleep(1)


if __name__ == "__main__":
    main()
