import logging
import threading
import time

from SMK_ADAPTERS.common.config import loadSecretFile
from SMK_ADAPTERS.common.constants import (
    ADAPTER_BY_PLATFORM_AND_ROLE,
    QUEUE_BY_PLATFORM_AND_ROLE,
    VK_ADMIN_QUEUE_NAME,
    VK_USER_QUEUE_NAME,
)
from SMK_ADAPTERS.common.http_client import SmcApiClient
from SMK_ADAPTERS.common.macros import TriggerUser, buildVkTriggerUser, replaceUserMacros
from SMK_ADAPTERS.common.models import IncomingMessage, QueueMessage
from SMK_ADAPTERS.common.parsers import BackendResponseParser
from SMK_ADAPTERS.common.rabbit import RabbitMqBus
from SMK_ADAPTERS.vk_adapter.client import VkApiError, VkBotClient
from SMK_ADAPTERS.vk_adapter.long_poll import NewLongPoll
from SMK_ADAPTERS.vk_adapter.settings import loadSettings


LOGGER = logging.getLogger(__name__)

adapterName: str = "vk_user"
queueName: str = "smc_vk_user"
adapterRole: str = "USER"
VK_QUEUE_DEFAULT_ADAPTERS = {
    VK_USER_QUEUE_NAME: "vk_user",
    VK_ADMIN_QUEUE_NAME: "vk_admin",
}
VK_SUPPORTED_ADAPTERS = set(VK_QUEUE_DEFAULT_ADAPTERS.values())

apiClient: SmcApiClient | None = None
messageParser: BackendResponseParser | None = None
vkClient: VkBotClient | None = None
publisherBus: RabbitMqBus | None = None
consumerBuses: dict[str, RabbitMqBus] = {}
longPoll: NewLongPoll | None = None


def getStarted():
    global adapterName
    global queueName
    global adapterRole
    global apiClient
    global messageParser
    global vkClient
    global publisherBus
    global consumerBuses
    global longPoll

    settings = loadSettings()
    token = loadSecretFile(settings.vk.token_file)
    adapterRole = normalizeRole(settings.vk.adapter_role)
    adapterName = ADAPTER_BY_PLATFORM_AND_ROLE[("VK", adapterRole)]
    queueName = QUEUE_BY_PLATFORM_AND_ROLE[("VK", adapterRole)]

    vkClient = VkBotClient(token=token)
    apiClient = SmcApiClient(settings.common.api)
    messageParser = BackendResponseParser()
    publisherBus = RabbitMqBus(settings.common.rabbit)
    consumerBuses = {
        VK_USER_QUEUE_NAME: RabbitMqBus(settings.common.rabbit),
        VK_ADMIN_QUEUE_NAME: RabbitMqBus(settings.common.rabbit),
    }
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
    queueMessage = messageParser.parseForAdminQueue(response, adapterName, triggerUser)
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

    for receiver in response.distribution.receivers:
        if shouldSkipDistributionReceiver(response, receiver):
            LOGGER.debug(
                "Получатель рассылки пропущен из-за sendToHimself=false: receiver=%s",
                receiver.receiver_id,
            )
            continue

        queueNameForReceiver = QUEUE_BY_PLATFORM_AND_ROLE.get((receiver.platform, receiver.role))
        adapterNameForReceiver = ADAPTER_BY_PLATFORM_AND_ROLE.get((receiver.platform, receiver.role))
        if queueNameForReceiver is None or adapterNameForReceiver is None:
            LOGGER.warning(
                "Получатель рассылки пропущен: неизвестная связка platform=%s, role=%s",
                receiver.platform,
                receiver.role,
            )
            continue

        queueMessage = QueueMessage.create(
            recipient_id=receiver.receiver_id,
            text=replaceUserMacros(response.distribution.text, triggerUser),
            adapter=adapterNameForReceiver,
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
        publisherBus.publishJson(queueNameForReceiver, queueMessage.toDict())


def shouldSkipDistributionReceiver(response, receiver) -> bool:
    if response.distribution is None:
        return False

    if response.distribution.send_to_himself:
        return False

    return response.recipient_id == receiver.receiver_id


def handleQueueMessage(payload: dict, defaultAdapter: str):
    if vkClient is None:
        raise RuntimeError("Адаптер не был запущен через getStarted")

    LOGGER.debug("Получено сообщение из RabbitMQ: %s", payload)

    message = QueueMessage.fromDict(payload, default_adapter=defaultAdapter)
    if message.adapter not in VK_SUPPORTED_ADAPTERS:
        LOGGER.debug("Сообщение очереди пропущено: оно предназначено для адаптера %s", message.adapter)
        return

    try:
        sendQueueMessageToVk(message)
    except VkApiError as exc:
        if exc.error_code == 911:
            LOGGER.error("VK отклонил сообщение без возможности повтора: %s", exc)
            return

        LOGGER.exception("VK отклонил сообщение")
        raise


def sendQueueMessageToVk(message: QueueMessage):
    if vkClient is None or apiClient is None:
        raise RuntimeError("Адаптер не был запущен через getStarted")

    for previewMessage in message.preview_messages:
        vkClient.sendMessage(chat_id=message.recipient_id, text=previewMessage)

    if message.files_ids:
        files = loadFiles(message.files_ids)
        vkClient.sendImagesWithText(
            chat_id=message.recipient_id,
            files=files,
            text=message.text,
            inline_elements=message.inline_elements,
            reply_elements=message.reply_elements,
        )
        return

    vkClient.sendMessage(
        chat_id=message.recipient_id,
        text=message.text,
        inline_elements=message.inline_elements,
        reply_elements=message.reply_elements,
    )


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


def startRabbitListening(queueNameForListening: str, defaultAdapter: str, bus: RabbitMqBus):
    while True:
        try:
            bus.reconnectForever()
            bus.consumeJson(
                queueNameForListening,
                lambda payload: handleQueueMessage(payload, defaultAdapter),
            )
        except Exception:
            LOGGER.exception("Цикл чтения из RabbitMQ завершился ошибкой: queue=%s", queueNameForListening)
            time.sleep(5)


def startVkListening():
    if longPoll is None:
        raise RuntimeError("Адаптер не был запущен через getStarted")

    longPoll.listen(handleIncomingMessage)


def runAdapter():
    rabbitThreads = [
        threading.Thread(
            target=startRabbitListening,
            args=(queueNameForListening, defaultAdapter, consumerBuses[queueNameForListening]),
            name=f"vk-rabbit-consumer-{defaultAdapter}",
            daemon=True,
        )
        for queueNameForListening, defaultAdapter in VK_QUEUE_DEFAULT_ADAPTERS.items()
    ]
    vkThread = threading.Thread(target=startVkListening, name="vk-long-poll", daemon=True)

    for rabbitThread in rabbitThreads:
        rabbitThread.start()

    vkThread.start()

    while vkThread.is_alive() and all(rabbitThread.is_alive() for rabbitThread in rabbitThreads):
        time.sleep(1)


def normalizeRole(role: str) -> str:
    role = role.upper()
    if role == "SUPER_ADMIN":
        return "SUPER_ADMIN"
    if role == "ADMIN":
        return "ADMIN"

    return "USER"
