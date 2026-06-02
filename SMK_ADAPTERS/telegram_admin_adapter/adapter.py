import logging
import threading
import time

from SMK_ADAPTERS.common.config import loadSecretFile
from SMK_ADAPTERS.common.constants import ADMIN_QUEUE_NAME, REPLY_KEYBOARD_HELP_TEXT
from SMK_ADAPTERS.common.http_client import SmcApiClient
from SMK_ADAPTERS.common.models import IncomingMessage, QueueMessage
from SMK_ADAPTERS.common.parsers import BackendResponseParser
from SMK_ADAPTERS.common.rabbit import RabbitMqBus
from SMK_ADAPTERS.telegram_admin_adapter.async_runtime import TelegramAsyncRuntime
from SMK_ADAPTERS.telegram_admin_adapter.client import TelegramApiError, TelegramBotClient
from SMK_ADAPTERS.telegram_admin_adapter.long_poll import NewLongPoll
from SMK_ADAPTERS.telegram_admin_adapter.settings import loadSettings


LOGGER = logging.getLogger(__name__)
ADAPTER_NAME = "telegram_admin"

apiClient: SmcApiClient | None = None
messageParser: BackendResponseParser | None = None
telegramClient: TelegramBotClient | None = None
telegramRuntime: TelegramAsyncRuntime | None = None
publisherBus: RabbitMqBus | None = None
consumerBus: RabbitMqBus | None = None
longPoll: NewLongPoll | None = None


def getStarted():
    global apiClient
    global messageParser
    global telegramClient
    global telegramRuntime
    global publisherBus
    global consumerBus
    global longPoll

    settings = loadSettings()
    token = loadSecretFile(settings.telegram.token_file)

    telegramRuntime = TelegramAsyncRuntime()
    telegramRuntime.start()
    telegramClient = TelegramBotClient(
        token=token,
        runtime=telegramRuntime,
        timeout_seconds=settings.common.api.timeout_seconds,
    )
    apiClient = SmcApiClient(settings.common.api)
    messageParser = BackendResponseParser()

    publisherBus = RabbitMqBus(settings.common.rabbit)
    consumerBus = RabbitMqBus(settings.common.rabbit)

    longPoll = NewLongPoll(
        client=telegramClient,
        adapter_name=ADAPTER_NAME,
        poll_timeout_seconds=settings.telegram.poll_timeout_seconds,
        retry_delay_seconds=settings.telegram.retry_delay_seconds,
    )


def handleIncomingMessage(message: IncomingMessage):
    if apiClient is None or messageParser is None or publisherBus is None:
        raise RuntimeError("Адаптер не был запущен через getStarted")

    LOGGER.debug(
        "Получено сообщение из Telegram: sender_id=%s, external_message_id=%s, text=%s",
        message.sender_id,
        message.external_message_id,
        message.text,
    )

    response = apiClient.sendAdminMessage(message)
    queueMessage = messageParser.parseForAdminQueue(response, ADAPTER_NAME)

    if queueMessage is None:
        LOGGER.info("Ответ smc.api не сформировал сообщение для очереди администратора")
        return

    publisherBus.publishJson(ADMIN_QUEUE_NAME, queueMessage.toDict())


def handleQueueMessage(payload: dict):
    if telegramClient is None:
        raise RuntimeError("Адаптер не был запущен через getStarted")

    LOGGER.debug("Получено сообщение из RabbitMQ: %s", payload)

    message = QueueMessage.fromDict(payload, default_adapter=ADAPTER_NAME)
    if message.adapter != ADAPTER_NAME:
        LOGGER.debug("Сообщение очереди пропущено: оно предназначено для адаптера %s", message.adapter)
        return

    try:
        sendQueueMessageToTelegram(message)
    except TelegramApiError as exc:
        if exc.status_code == 400:
            LOGGER.error("Telegram отклонил сообщение без возможности повтора: %s", exc)
            return
        raise


def sendQueueMessageToTelegram(message: QueueMessage):
    if telegramClient is None:
        raise RuntimeError("Адаптер не был запущен через getStarted")

    hasInlineKeyboard = bool(message.inline_elements)
    hasReplyKeyboard = bool(message.reply_elements)
    previewMessages = list(message.preview_messages)

    if hasInlineKeyboard and hasReplyKeyboard:
        sendPreviewMessages(message.recipient_id, previewMessages)
        telegramClient.sendMessage(
            chat_id=message.recipient_id,
            text=message.text,
            inline_elements=message.inline_elements,
        )
        telegramClient.sendMessage(
            chat_id=message.recipient_id,
            text=REPLY_KEYBOARD_HELP_TEXT,
            reply_elements=message.reply_elements,
        )
        return

    sendPreviewMessages(message.recipient_id, previewMessages)

    telegramClient.sendMessage(
        chat_id=message.recipient_id,
        text=message.text,
        inline_elements=message.inline_elements,
        reply_elements=message.reply_elements,
    )


def sendPreviewMessages(recipientId: str, previewMessages: list[str]):
    if telegramClient is None:
        raise RuntimeError("Адаптер не был запущен через getStarted")

    for previewMessage in previewMessages:
        telegramClient.sendMessage(
            chat_id=recipientId,
            text=previewMessage,
        )


def startRabbitListening():
    if consumerBus is None:
        raise RuntimeError("Адаптер не был запущен через getStarted")

    while True:
        try:
            consumerBus.reconnectForever()
            consumerBus.consumeJson(ADMIN_QUEUE_NAME, handleQueueMessage)
        except Exception:
            LOGGER.exception("Цикл чтения из RabbitMQ завершился ошибкой")
            time.sleep(5)


def startTelegramListening():
    if longPoll is None:
        raise RuntimeError("Адаптер не был запущен через getStarted")

    longPoll.listen(handleIncomingMessage)


def runAdapter():
    rabbitThread = threading.Thread(target=startRabbitListening, name="telegram-admin-rabbit-consumer", daemon=True)
    telegramThread = threading.Thread(target=startTelegramListening, name="telegram-admin-long-poll", daemon=True)

    rabbitThread.start()
    telegramThread.start()

    while rabbitThread.is_alive() and telegramThread.is_alive():
        time.sleep(1)
