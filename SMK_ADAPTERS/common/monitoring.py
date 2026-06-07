import json
import logging
import queue
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from SMK_ADAPTERS.common.config import MonitoringConfig
from SMK_ADAPTERS.common.macros import TriggerUser


LOGGER = logging.getLogger(__name__)
TIME_FORMAT = "%d.%m.%Y %H:%M:%S"
MAX_MESSAGE_LENGTH = 4000
TECHNICAL_ALERT_COOLDOWN_SECONDS = 600
APPLICATION_LOGGER_PREFIX = "SMK_ADAPTERS."
IGNORED_LOG_FRAGMENTS = (
    "Telegram long poll",
    "Request timeout",
    "HTTP Client says - Request timeout",
)

_reporter: "MonitoringReporter | None" = None


@dataclass(frozen=True, slots=True)
class MonitoringEvent:
    level: str
    channel: str
    message: str
    triggered_by: TriggerUser | None = None
    time: str = ""

    def toPayload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "level": self.level,
            "channel": self.channel,
            "message": self.message,
            "time": self.time or datetime.now().strftime(TIME_FORMAT),
        }
        if self.triggered_by is not None:
            payload["triggeredBy"] = {
                "name": self.triggered_by.name,
                "link": self.triggered_by.link,
            }

        return payload


class MonitoringReporter:
    def __init__(self, config: MonitoringConfig, channel: str) -> None:
        self.config = config
        self.channel = channel
        self.events: queue.Queue[MonitoringEvent] = queue.Queue(maxsize=config.queue_size)
        self.thread = threading.Thread(target=self.run, name="monitoring-reporter", daemon=True)

    def start(self) -> None:
        if self.config.enabled:
            self.thread.start()

    def emit(
        self,
        level: str,
        message: str,
        triggered_by: TriggerUser | None = None,
        channel: str | None = None,
    ) -> None:
        if not self.config.enabled:
            return

        event = MonitoringEvent(
            level=level.upper(),
            channel=channel or self.channel,
            message=message,
            triggered_by=triggered_by,
        )
        try:
            self.events.put_nowait(event)
        except queue.Full:
            LOGGER.warning("Очередь мониторинга заполнена, событие пропущено: level=%s", level)

    def run(self) -> None:
        while True:
            event = self.events.get()
            try:
                self.send(event)
            except Exception:
                LOGGER.debug("Не удалось отправить событие мониторинга", exc_info=True)
            finally:
                self.events.task_done()

    def send(self, event: MonitoringEvent) -> None:
        body = json.dumps(event.toPayload(), ensure_ascii=False).encode("utf-8")
        request = Request(
            self.buildUrl(),
            data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "api-key": self.config.api_key,
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=self.config.timeout_seconds) as response:
                response.read()
        except HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"monitoring вернул статус {exc.code}: {details}") from exc
        except URLError as exc:
            raise RuntimeError(f"monitoring недоступен: {exc.reason}") from exc

    def buildUrl(self) -> str:
        return f"{self.config.base_url}/{self.config.endpoint.lstrip('/')}"


class MonitoringLogHandler(logging.Handler):
    def __init__(self, level: int = logging.NOTSET) -> None:
        super().__init__(level)
        self.lastEventAt: dict[str, float] = {}

    def emit(self, record: logging.LogRecord) -> None:
        if record.name == __name__ or record.name.startswith(f"{__name__}."):
            return

        if record.levelno < logging.ERROR:
            return

        if not record.name.startswith(APPLICATION_LOGGER_PREFIX):
            return

        normalized = normalizeLogRecord(record)
        if normalized is None:
            return

        level, message, dedupKey = normalized
        if not self.shouldSend(dedupKey):
            return

        if shouldIgnoreLogMessage(message):
            return

        emitMonitoringEvent(level, message)

    def shouldSend(self, key: str) -> bool:
        now = time.monotonic()
        lastSentAt = self.lastEventAt.get(key)
        if lastSentAt is not None and now - lastSentAt < TECHNICAL_ALERT_COOLDOWN_SECONDS:
            return False

        self.lastEventAt[key] = now
        return True


def configureMonitoring(config: MonitoringConfig, channel: str) -> None:
    global _reporter

    _reporter = MonitoringReporter(config, channel)
    _reporter.start()

    handler = MonitoringLogHandler(level=logging.ERROR)
    handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
    logging.getLogger().addHandler(handler)


def emitMonitoringEvent(
    level: str,
    message: str,
    triggered_by: TriggerUser | None = None,
    channel: str | None = None,
) -> None:
    if _reporter is None:
        return

    _reporter.emit(level, trimMessage(message), triggered_by, channel)


def shouldIgnoreLogMessage(message: str) -> bool:
    return any(fragment in message for fragment in IGNORED_LOG_FRAGMENTS)


def normalizeLogRecord(record: logging.LogRecord) -> tuple[str, str, str] | None:
    if not record.name.startswith(APPLICATION_LOGGER_PREFIX):
        return None

    rawMessage = record.getMessage()
    if shouldIgnoreLogMessage(rawMessage):
        return None

    if record.name == "SMK_ADAPTERS.common.rabbit":
        return normalizeRabbitMqLog(rawMessage)

    if record.name.endswith(".long_poll"):
        return (
            "WARN",
            "Long poll адаптера перезапускается после ошибки. Если бот отвечает, действие не требуется.",
            f"{record.name}:long-poll",
        )

    if record.exc_info:
        excType = record.exc_info[0].__name__
        excMessage = str(record.exc_info[1])
        return (
            record.levelname,
            f"{rawMessage}. Причина: {excType}: {excMessage}",
            f"{record.name}:{excType}:{rawMessage}",
        )

    return (record.levelname, rawMessage, f"{record.name}:{rawMessage}")


def normalizeRabbitMqLog(message: str) -> tuple[str, str, str]:
    if "подключ" in message:
        return (
            "WARN",
            "RabbitMQ временно недоступен. Адаптер пытается переподключиться, сообщения останутся в очередях.",
            "rabbitmq:connection",
        )

    if "опубликовать" in message:
        return (
            "WARN",
            "Не удалось опубликовать сообщение в RabbitMQ. Адаптер восстановит соединение и повторит работу.",
            "rabbitmq:publish",
        )

    if "обработать сообщение RabbitMQ" in message:
        return (
            "ERROR",
            "Не удалось обработать сообщение из RabbitMQ. Сообщение возвращено в очередь для повторной обработки.",
            "rabbitmq:consume",
        )

    return (
        "WARN",
        "RabbitMQ сообщил о техническом сбое. Адаптер продолжает работу и пытается восстановить соединение.",
        "rabbitmq:generic",
    )


def trimMessage(message: str) -> str:
    if len(message) <= MAX_MESSAGE_LENGTH:
        return message

    return f"{message[:MAX_MESSAGE_LENGTH]}..."
