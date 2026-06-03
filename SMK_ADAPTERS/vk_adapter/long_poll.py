import logging
import time
import base64
from collections.abc import Callable
from urllib.request import urlopen

from vk_api.longpoll import VkEventType, VkLongPoll

from SMK_ADAPTERS.common.models import IncomingMessage, MessageFile
from SMK_ADAPTERS.vk_adapter.client import VkBotClient


LOGGER = logging.getLogger(__name__)


class NewLongPoll(VkLongPoll):
    def __init__(self, client: VkBotClient, adapter_name: str, retry_delay_seconds: float = 3) -> None:
        super().__init__(client.authorize)
        self.client = client
        self.adapterName = adapter_name
        self.retryDelaySeconds = retry_delay_seconds

    def listen(self, handler: Callable[[IncomingMessage], None]) -> None:
        while True:
            try:
                for event in self.check():
                    message = self.eventToIncoming(event)
                    if message is not None:
                        self.handleMessage(handler, message)
            except Exception:
                LOGGER.exception("Итерация VK long poll завершилась ошибкой")
                time.sleep(self.retryDelaySeconds)

    def handleMessage(self, handler: Callable[[IncomingMessage], None], message: IncomingMessage) -> None:
        try:
            handler(message)
        except Exception:
            LOGGER.exception(
                "Обработка сообщения VK завершилась ошибкой: sender_id=%s, external_message_id=%s",
                message.sender_id,
                message.external_message_id,
            )

    def eventToIncoming(self, event) -> IncomingMessage | None:
        if event.type != VkEventType.MESSAGE_NEW or not event.to_me:
            return None

        text = event.text or ""
        attachments = self.extractAttachments(event)
        if not text and not attachments:
            return None

        return IncomingMessage(
            adapter=self.adapterName,
            channel="vk",
            sender_id=str(event.user_id),
            text=text,
            attachments=attachments,
            external_message_id=str(getattr(event, "message_id", "")) or None,
            metadata={
                "vk": {
                    "userId": event.user_id,
                    "peerId": getattr(event, "peer_id", None),
                    "attachments": getattr(event, "attachments", None),
                }
            },
        )

    def extractAttachments(self, event) -> list[MessageFile]:
        messageId = getattr(event, "message_id", None)
        if messageId is None:
            return []

        try:
            response = self.client.session.messages.getById(message_ids=messageId, preview_length=0)
        except Exception:
            LOGGER.exception("Не удалось получить вложения VK")
            return []

        items = response.get("items") or []
        if not items:
            return []

        attachments = items[0].get("attachments") or []
        result: list[MessageFile] = []
        for attachment in attachments:
            parsedAttachment = self.parseAttachment(attachment)
            if parsedAttachment is not None:
                result.append(parsedAttachment)

        return result

    def parseAttachment(self, attachment: dict) -> MessageFile | None:
        attachmentType = attachment.get("type")
        if attachmentType == "photo":
            return self.parsePhotoAttachment(attachment.get("photo") or {})
        if attachmentType == "doc":
            return self.parseDocumentAttachment(attachment.get("doc") or {})

        return None

    def parsePhotoAttachment(self, photo: dict) -> MessageFile | None:
        sizes = photo.get("sizes") or []
        if not sizes:
            return None

        size = max(sizes, key=lambda item: int(item.get("width") or 0) * int(item.get("height") or 0))
        url = size.get("url")
        if not url:
            return None

        content = self.downloadFile(url)
        return MessageFile(
            file_name=f"vk_photo_{photo.get('owner_id')}_{photo.get('id')}.jpg",
            mime_type="image/jpeg",
            content_base64=base64.b64encode(content).decode("ascii"),
        )

    def parseDocumentAttachment(self, document: dict) -> MessageFile | None:
        url = document.get("url")
        if not url:
            return None

        content = self.downloadFile(url)
        title = str(document.get("title") or document.get("id") or "vk_document")
        extension = str(document.get("ext") or "").strip(".")
        fileName = f"{title}.{extension}" if extension and not title.endswith(f".{extension}") else title

        return MessageFile(
            file_name=fileName,
            mime_type="application/octet-stream",
            content_base64=base64.b64encode(content).decode("ascii"),
        )

    def downloadFile(self, url: str) -> bytes:
        with urlopen(url, timeout=10) as response:
            return response.read()


VkLongPollAdapter = NewLongPoll
