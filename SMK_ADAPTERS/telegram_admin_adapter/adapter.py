import logging
import threading
import time

from SMK_ADAPTERS.common.config import loadSecretFile
from SMK_ADAPTERS.common.constants import (
    ADAPTER_BY_PLATFORM_AND_ROLE,
    REPLY_KEYBOARD_HELP_TEXT,
    buildQueueByPlatformAndRole,
)
from SMK_ADAPTERS.common.http_client import SmcApiClient
from SMK_ADAPTERS.common.macros import TriggerUser, buildTelegramTriggerUser, replaceUserMacros
from SMK_ADAPTERS.common.models import DistributionReceiver, IncomingMessage, QueueMessage
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
adminQueueName: str = "smc_tg_admin_panel"
queueByPlatformAndRole: dict[tuple[str, str], str] = {}


def getStarted():
    global apiClient
    global messageParser
    global telegramClient
    global telegramRuntime
    global publisherBus
    global consumerBus
    global longPoll
    global adminQueueName
    global queueByPlatformAndRole

    settings = loadSettings()
    token = loadSecretFile(settings.telegram.token_file)
    queueByPlatformAndRole = buildQueueByPlatformAndRole(settings.common.deployment.queue_prefix)
    adminQueueName = queueByPlatformAndRole[("TG", "ADMIN")]

    telegramRuntime = TelegramAsyncRuntime()
    telegramRuntime.start()
    telegramClient = TelegramBotClient(
        token=token,
        runtime=telegramRuntime,
        timeout_seconds=settings.common.api.timeout_seconds,
        proxy_url=settings.telegram.proxy_url,
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

    triggerUser = buildTelegramTriggerUser(message)
    response = apiClient.sendAdminMessage(message)
    publishDistributionMessages(response, triggerUser)
    queueMessage = messageParser.parseForAdminQueue(
        response,
        ADAPTER_NAME,
        triggerUser,
        lambda platform, userId: resolveUserMacro(platform, userId, triggerUser),
    )

    if queueMessage is None:
        LOGGER.info("Ответ smc.api не сформировал сообщение для очереди администратора")
        return

    publisherBus.publishJson(adminQueueName, queueMessage.toDict())


def publishDistributionMessages(response, triggerUser: TriggerUser | None = None):
    if publisherBus is None:
        raise RuntimeError("Адаптер не был запущен через getStarted")

    if response.distribution is None:
        return

    for receiver in response.distribution.receivers:
        if shouldSkipDistributionReceiver(response, receiver):
            LOGGER.debug(
                "Получатель рассылки пропущен из-за sendToHimself=false: receiver=%s",
                receiver.receiver_id,
            )
            continue

        queueName = getDistributionQueueName(receiver)
        adapterName = getDistributionAdapterName(receiver)
        if queueName is None or adapterName is None:
            LOGGER.warning(
                "Получатель рассылки пропущен: неизвестная связка platform=%s, role=%s",
                receiver.platform,
                receiver.role,
            )
            continue

        queueMessage = QueueMessage.create(
            recipient_id=receiver.receiver_id,
            text=replaceUserMacros(
                response.distribution.text,
                triggerUser,
                lambda platform, userId: resolveUserMacro(platform, userId, triggerUser),
            ),
            adapter=adapterName,
            files_ids=response.distribution.files_ids,
            inline_elements=response.distribution.inline_elements or receiver.inline_elements,
            reply_elements=receiver.reply_elements,
            metadata={
                "source": "smc.api",
                "distribution": True,
                "platform": receiver.platform,
                "role": receiver.role,
            },
        )
        LOGGER.debug(
            "Публикация сообщения рассылки: queue=%s, receiver=%s, platform=%s, role=%s",
            queueName,
            receiver.receiver_id,
            receiver.platform,
            receiver.role,
        )
        publisherBus.publishJson(queueName, queueMessage.toDict())


def shouldSkipDistributionReceiver(response, receiver: DistributionReceiver) -> bool:
    if response.distribution is None:
        return False

    if response.distribution.send_to_himself:
        return False

    return response.platform == receiver.platform and response.recipient_id == receiver.receiver_id


def getDistributionQueueName(receiver: DistributionReceiver) -> str | None:
    return queueByPlatformAndRole.get((receiver.platform, receiver.role))


def getDistributionAdapterName(receiver: DistributionReceiver) -> str | None:
    return ADAPTER_BY_PLATFORM_AND_ROLE.get((receiver.platform, receiver.role))


def resolveUserMacro(platform: str, userId: str, triggerUser: TriggerUser | None = None) -> TriggerUser | None:
    if platform != "TG":
        return None

    if triggerUser is not None and triggerUser.user_id == userId:
        return triggerUser

    return TriggerUser(
        name=userId,
        user_id=userId,
        link=f"tg://user?id={userId}",
    )


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
    if telegramClient is None or apiClient is None:
        raise RuntimeError("Адаптер не был запущен через getStarted")

    hasInlineKeyboard = bool(message.inline_elements)
    hasReplyKeyboard = bool(message.reply_elements)
    previewMessages = [
        replaceUserMacros(previewMessage, None, resolveUserMacro)
        for previewMessage in message.preview_messages
    ]
    filesIds = list(message.files_ids)
    text = replaceUserMacros(message.text, None, resolveUserMacro)

    if hasInlineKeyboard and hasReplyKeyboard:
        sendPreviewMessages(message.recipient_id, previewMessages)
        if filesIds:
            sendFilesWithTargetMessage(
                recipientId=message.recipient_id,
                filesIds=filesIds,
                text=text,
                inlineElements=message.inline_elements,
            )
        else:
            telegramClient.sendMessage(
                chat_id=message.recipient_id,
                text=text,
                inline_elements=message.inline_elements,
            )
        telegramClient.sendMessage(
            chat_id=message.recipient_id,
            text=REPLY_KEYBOARD_HELP_TEXT,
            reply_elements=message.reply_elements,
        )
        return

    sendPreviewMessages(message.recipient_id, previewMessages)
    if filesIds:
        sendFilesWithTargetMessage(
            recipientId=message.recipient_id,
            filesIds=filesIds,
            text=text,
            inlineElements=message.inline_elements,
            replyElements=message.reply_elements,
        )
        return

    telegramClient.sendMessage(
        chat_id=message.recipient_id,
        text=text,
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


def sendFilesWithTargetMessage(
    recipientId: str,
    filesIds: list[str],
    text: str,
    inlineElements=None,
    replyElements=None,
):
    if telegramClient is None or apiClient is None:
        raise RuntimeError("Адаптер не был запущен через getStarted")

    files = loadFiles(filesIds)
    if len(files) == 1:
        content, fileName = files[0]
        telegramClient.sendImageWithText(
            chat_id=recipientId,
            content=content,
            file_name=fileName,
            text=text,
            inline_elements=inlineElements,
            reply_elements=replyElements,
        )
        return

    telegramClient.sendImagesWithText(
        chat_id=recipientId,
        files=files,
        text=text,
    )

    if inlineElements:
        LOGGER.debug("Inline-клавиатура не отправлена с альбомом: Telegram не поддерживает reply_markup для media group")


def loadFiles(filesIds: list[str]) -> list[tuple[bytes, str]]:
    if apiClient is None:
        raise RuntimeError("Адаптер не был запущен через getStarted")

    files: list[tuple[bytes, str]] = []
    for index, fileId in enumerate(filesIds, start=1):
        content = apiClient.getFile(fileId)
        files.append((content, makeFileName(fileId, index, content)))

    return files


def makeFileName(fileId: str, index: int, content: bytes) -> str:
    extension = detectImageExtension(content)
    return f"{fileId}-{index}.{extension}"


def detectImageExtension(content: bytes) -> str:
    if content.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if content.startswith(b"GIF87a") or content.startswith(b"GIF89a"):
        return "gif"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "webp"

    return "bin"


def startRabbitListening():
    if consumerBus is None:
        raise RuntimeError("Адаптер не был запущен через getStarted")

    while True:
        try:
            consumerBus.reconnectForever()
            consumerBus.consumeJson(adminQueueName, handleQueueMessage)
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
