import json
import logging
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Iterator


LOG_PLATFORM: ContextVar[str | None] = ContextVar("log_platform", default=None)
LOG_USER_ID: ContextVar[str | None] = ContextVar("log_user_id", default=None)
LOG_MESSAGE_TYPE: ContextVar[str | None] = ContextVar("log_message_type", default=None)


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "thread": record.threadName,
            "message": record.getMessage(),
        }

        platform = getattr(record, "platform", None) or LOG_PLATFORM.get()
        userId = getattr(record, "userId", None) or LOG_USER_ID.get()
        messageType = getattr(record, "messageType", None) or LOG_MESSAGE_TYPE.get()

        if platform is not None:
            payload["platform"] = platform
        if userId is not None:
            payload["userId"] = userId
        if messageType is not None:
            payload["messageType"] = messageType

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)


def configureJsonLogging(logLevel: int) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonLogFormatter())

    rootLogger = logging.getLogger()
    rootLogger.handlers.clear()
    rootLogger.addHandler(handler)
    rootLogger.setLevel(logLevel)


@contextmanager
def loggingContext(platform: str | None = None, userId: str | None = None, messageType: str | None = None) -> Iterator[None]:
    platformToken = LOG_PLATFORM.set(platform)
    userIdToken = LOG_USER_ID.set(userId)
    messageTypeToken = LOG_MESSAGE_TYPE.set(messageType)

    try:
        yield
    finally:
        LOG_PLATFORM.reset(platformToken)
        LOG_USER_ID.reset(userIdToken)
        LOG_MESSAGE_TYPE.reset(messageTypeToken)
