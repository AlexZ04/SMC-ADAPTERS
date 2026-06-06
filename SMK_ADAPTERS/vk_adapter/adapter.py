import logging
import threading
import time

from SMK_ADAPTERS.common.config import loadSecretFile
from SMK_ADAPTERS.common.constants import (
    ADAPTER_BY_PLATFORM_AND_ROLE,
    ADAPTER_BY_PLATFORM_AND_CHANNEL,
    ADMIN_CHANNEL,
    USER_ROLE,
    buildQueueByPlatformAndChannel,
    buildQueueByPlatformAndRole,
)
from SMK_ADAPTERS.common.http_client import SmcApiClient
from SMK_ADAPTERS.common.macros import TriggerUser, buildVkTriggerUser, replaceUserMacros
from SMK_ADAPTERS.common.models import IncomingMessage, QueueMessage
from SMK_ADAPTERS.common.monitoring import emitMonitoringEvent
from SMK_ADAPTERS.common.parsers import BackendResponseParser
from SMK_ADAPTERS.common.rabbit import RabbitMqBus
from SMK_ADAPTERS.vk_adapter.client import VkApiError, VkBotClient
from SMK_ADAPTERS.vk_adapter.long_poll import NewLongPoll
from SMK_ADAPTERS.vk_adapter.settings import loadSettings


LOGGER = logging.getLogger(__name__)
VK_PERMISSION_DENIED_ERROR_CODE = 901
VK_NON_RETRYABLE_ERROR_CODES = {VK_PERMISSION_DENIED_ERROR_CODE, 911}

adapterName: str = "vk_user"
queueName: str = "smc_vk_user"
adapterRole: str = "USER"

apiClient: SmcApiClient | None = None
messageParser: BackendResponseParser | None = None
vkClient: VkBotClient | None = None
publisherBus: RabbitMqBus | None = None
consumerBus: RabbitMqBus | None = None
longPoll: NewLongPoll | None = None
queueByPlatformAndRole: dict[tuple[str, str], str] = {}
queueByPlatformAndChannel: dict[tuple[str, str], str] = {}


def getStarted():
    global adapterName
    global queueName
    global adapterRole
    global apiClient
    global messageParser
    global vkClient
    global publisherBus
    global consumerBus
    global longPoll
    global queueByPlatformAndRole
    global queueByPlatformAndChannel

    settings = loadSettings()
    token = loadSecretFile(settings.vk.token_file)
    adapterRole = normalizeRole(settings.vk.adapter_role)
    adapterName = ADAPTER_BY_PLATFORM_AND_ROLE[("VK", adapterRole)]
    queueByPlatformAndRole = buildQueueByPlatformAndRole(settings.common.deployment.queue_prefix)
    queueByPlatformAndChannel = buildQueueByPlatformAndChannel(settings.common.deployment.queue_prefix)
    queueName = queueByPlatformAndRole[("VK", adapterRole)]

    vkClient = VkBotClient(token=token)
    apiClient = SmcApiClient(settings.common.api)
    messageParser = BackendResponseParser()
    publisherBus = RabbitMqBus(settings.common.rabbit)
    consumerBus = RabbitMqBus(settings.common.rabbit)
    longPoll = NewLongPoll(client=vkClient, adapter_name=adapterName)


def handleIncomingMessage(message: IncomingMessage):
    if apiClient is None or messageParser is None or publisherBus is None:
        raise RuntimeError("Адаптер не был запущен через getStarted")

    LOGGER.debug(
        "Получено сообщение из VK: sender_id=%s, external_message_id=%s, text=%s",
        message.sender_id,
        message.external_message_id,
        message.text,
    )

    triggerUser = getTriggerUser(message)

    if adapterRole in {"ADMIN", "SUPER_ADMIN"}:
        response = apiClient.sendAdminMessage(message)
    else:
        response = apiClient.sendUserMessage(message)

    publishDistributionMessages(response, triggerUser)
    queueMessage = messageParser.parseForAdminQueue(response, adapterName, triggerUser, resolveUserMacro)
    if queueMessage is None:
        LOGGER.info("Ответ smc.api не сформировал сообщение для очереди VK")
        return

    publisherBus.publishJson(queueName, queueMessage.toDict())


def getTriggerUser(message: IncomingMessage) -> TriggerUser:
    if vkClient is None:
        return buildVkTriggerUser(message.sender_id)

    try:
        return buildVkTriggerUser(message.sender_id, vkClient.getUserProfile(message.sender_id))
    except VkApiError:
        LOGGER.exception("Не удалось получить профиль пользователя VK для подстановки макросов: user_id=%s", message.sender_id)
        return buildVkTriggerUser(message.sender_id)


def publishDistributionMessages(response, triggerUser: TriggerUser | None = None):
    if publisherBus is None:
        raise RuntimeError("Адаптер не был запущен через getStarted")

    if response.distribution is None:
        return

    publishedCount = 0
    unknownRouteCount = 0
    for receiver in response.distribution.receivers:
        if shouldSkipDistributionReceiver(response, receiver):
            LOGGER.debug(
                "Получатель рассылки пропущен из-за sendToHimself=false: receiver=%s",
                receiver.receiver_id,
            )
            continue

        queueNameForReceiver = queueByPlatformAndChannel.get((receiver.platform, receiver.channel))
        adapterNameForReceiver = ADAPTER_BY_PLATFORM_AND_CHANNEL.get((receiver.platform, receiver.channel))
        if queueNameForReceiver is None or adapterNameForReceiver is None:
            unknownRouteCount += 1
            LOGGER.warning(
                "Получатель рассылки пропущен: неизвестная связка platform=%s, channel=%s",
                receiver.platform,
                receiver.channel,
            )
            continue

        queueMessage = QueueMessage.create(
            recipient_id=receiver.receiver_id,
            text=replaceUserMacros(response.distribution.text, triggerUser, resolveUserMacro),
            adapter=adapterNameForReceiver,
            files_ids=response.distribution.files_ids,
            inline_elements=response.distribution.inline_elements or receiver.inline_elements,
            reply_elements=receiver.reply_elements,
            metadata={
                "source": "smc.api",
                "distribution": True,
                "platform": receiver.platform,
                "role": receiver.role,
                "channel": receiver.channel,
            },
        )
        publisherBus.publishJson(queueNameForReceiver, queueMessage.toDict())
        publishedCount += 1

    if publishedCount > 0:
        emitMonitoringEvent(
            "INFO",
            f"Пользователь отправил рассылку: получателей={publishedCount}, файлов={len(response.distribution.files_ids)}",
            triggerUser,
        )

    if unknownRouteCount > 0:
        emitMonitoringEvent(
            "WARN",
            f"Рассылка частично пропущена: неизвестная связка platform+channel у получателей={unknownRouteCount}",
            triggerUser,
        )


def shouldSkipDistributionReceiver(response, receiver) -> bool:
    if response.distribution is None:
        return False

    if receiver.role == USER_ROLE and receiver.channel == ADMIN_CHANNEL:
        return True

    if response.distribution.send_to_himself:
        return False

    return response.platform == receiver.platform and response.recipient_id == receiver.receiver_id


def handleQueueMessage(payload: dict):
    if vkClient is None:
        raise RuntimeError("Адаптер не был запущен через getStarted")

    LOGGER.debug("Получено сообщение из RabbitMQ: %s", payload)

    message = QueueMessage.fromDict(payload, default_adapter=adapterName)
    if message.adapter != adapterName:
        LOGGER.debug("Сообщение очереди пропущено: оно предназначено для адаптера %s", message.adapter)
        return

    try:
        sendQueueMessageToVk(message)
    except VkApiError as exc:
        if exc.error_code == VK_PERMISSION_DENIED_ERROR_CODE:
            LOGGER.debug("VK запретил отправку сообщения пользователю: %s", exc)
            return

        if exc.error_code in VK_NON_RETRYABLE_ERROR_CODES:
            LOGGER.error("VK отклонил сообщение без возможности повтора: %s", exc)
            return

        LOGGER.exception("VK отклонил сообщение")
        raise


def sendQueueMessageToVk(message: QueueMessage):
    if vkClient is None or apiClient is None:
        raise RuntimeError("Адаптер не был запущен через getStarted")

    for previewMessage in message.preview_messages:
        previewText = replaceUserMacros(previewMessage.response_text, None, resolveUserMacro)
        vkClient.sendMessage(
            chat_id=message.recipient_id,
            text=previewText,
            inline_elements=previewMessage.inline_elements,
        )

    text = replaceUserMacros(message.text, None, resolveUserMacro)

    if message.files_ids:
        files = loadFiles(message.files_ids)
        vkClient.sendImagesWithText(
            chat_id=message.recipient_id,
            files=files,
            text=text,
            inline_elements=message.inline_elements,
            reply_elements=message.reply_elements,
        )
        return

    vkClient.sendMessage(
        chat_id=message.recipient_id,
        text=text,
        inline_elements=message.inline_elements,
        reply_elements=message.reply_elements,
    )


def resolveUserMacro(platform: str, userId: str) -> TriggerUser | None:
    if platform == "VK":
        if vkClient is None:
            return buildVkTriggerUser(userId)

        try:
            return buildVkTriggerUser(userId, vkClient.getUserProfile(userId))
        except VkApiError:
            LOGGER.exception("Не удалось получить профиль пользователя VK для подстановки макросов: user_id=%s", userId)
            return buildVkTriggerUser(userId)

    return None


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

    return "bin"


def startRabbitListening():
    if consumerBus is None:
        raise RuntimeError("Адаптер не был запущен через getStarted")

    while True:
        try:
            consumerBus.reconnectForever()
            consumerBus.consumeJson(queueName, handleQueueMessage)
        except Exception:
            LOGGER.exception("Цикл чтения из RabbitMQ завершился ошибкой: queue=%s", queueName)
            time.sleep(5)


def startVkListening():
    if longPoll is None:
        raise RuntimeError("Адаптер не был запущен через getStarted")

    longPoll.listen(handleIncomingMessage)


def runAdapter():
    rabbitThread = threading.Thread(
        target=startRabbitListening,
        name=f"vk-rabbit-consumer-{adapterName}",
        daemon=True,
    )
    vkThread = threading.Thread(target=startVkListening, name="vk-long-poll", daemon=True)

    rabbitThread.start()
    vkThread.start()

    while vkThread.is_alive() and rabbitThread.is_alive():
        time.sleep(1)


def normalizeRole(role: str) -> str:
    role = role.upper()
    if role == "SUPER_ADMIN":
        return "SUPER_ADMIN"
    if role == "ADMIN":
        return "ADMIN"

    return "USER"
