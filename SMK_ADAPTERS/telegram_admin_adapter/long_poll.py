import asyncio
import base64
import logging
from io import BytesIO
from collections.abc import Callable

from aiogram import Dispatcher
from aiogram.types import CallbackQuery, Document, Message, PhotoSize

from SMK_ADAPTERS.common.models import IncomingMessage, MessageFile
from SMK_ADAPTERS.telegram_admin_adapter.client import TelegramApiError, TelegramBotClient


LOGGER = logging.getLogger(__name__)


class NewLongPoll:
    def __init__(
        self,
        client: TelegramBotClient,
        adapter_name: str,
        poll_timeout_seconds: int,
        retry_delay_seconds: float,
    ) -> None:
        self.client = client
        self.adapterName = adapter_name
        self.pollTimeoutSeconds = poll_timeout_seconds
        self.retryDelaySeconds = retry_delay_seconds
        self.dispatcher = Dispatcher()
        self.mediaGroupMessages: dict[str, list[Message]] = {}
        self.mediaGroupTasks: dict[str, asyncio.Task] = {}

    def listen(self, handler: Callable[[IncomingMessage], None]) -> None:
        self.registerHandlers(handler)
        self.client.runtime.run(self.listenAsync())

    async def listenAsync(self) -> None:
        while True:
            try:
                await self.dispatcher.start_polling(
                    self.client.bot,
                    polling_timeout=self.pollTimeoutSeconds,
                    allowed_updates=["message", "callback_query"],
                    handle_signals=False,
                )
            except RuntimeError as exc:
                LOGGER.warning("%s. Следующая попытка через %s сек.", exc, self.retryDelaySeconds)
                await asyncio.sleep(self.retryDelaySeconds)
            except Exception:
                LOGGER.exception("Telegram long poll завершился ошибкой")
                await asyncio.sleep(self.retryDelaySeconds)

    def registerHandlers(self, handler: Callable[[IncomingMessage], None]) -> None:
        @self.dispatcher.message()
        async def onMessage(message: Message) -> None:
            if message.media_group_id:
                await self.handleMediaGroupMessage(message, handler)
                return

            incomingMessage = await self.messageToIncoming(message)
            if incomingMessage is None:
                return

            await self.callHandler(handler, incomingMessage)

        @self.dispatcher.callback_query()
        async def onCallback(callback_query: CallbackQuery) -> None:
            incomingMessage = self.callbackToIncoming(callback_query)
            if incomingMessage is None:
                return

            try:
                await self.client.answerCallbackQueryAsync(callback_query.id)
            except TelegramApiError:
                LOGGER.exception("Telegram не подтвердил callback query")

            await self.callHandler(handler, incomingMessage)

    async def callHandler(self, handler: Callable[[IncomingMessage], None], message: IncomingMessage) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, handler, message)

    async def handleMediaGroupMessage(self, message: Message, handler: Callable[[IncomingMessage], None]) -> None:
        mediaGroupId = str(message.media_group_id)
        self.mediaGroupMessages.setdefault(mediaGroupId, []).append(message)

        if mediaGroupId in self.mediaGroupTasks:
            return

        self.mediaGroupTasks[mediaGroupId] = asyncio.create_task(self.flushMediaGroup(mediaGroupId, handler))

    async def flushMediaGroup(self, mediaGroupId: str, handler: Callable[[IncomingMessage], None]) -> None:
        await asyncio.sleep(1)

        messages = self.mediaGroupMessages.pop(mediaGroupId, [])
        self.mediaGroupTasks.pop(mediaGroupId, None)
        if not messages:
            return

        incomingMessage = await self.mediaGroupToIncoming(messages)
        if incomingMessage is None:
            return

        await self.callHandler(handler, incomingMessage)

    async def mediaGroupToIncoming(self, messages: list[Message]) -> IncomingMessage | None:
        messages.sort(key=lambda item: item.message_id)
        firstMessage = messages[0]
        text = self.findMediaGroupText(messages)
        attachments: list[MessageFile] = []

        for message in messages:
            attachments.extend(await self.extractAttachments(message))

        if not text and not attachments:
            return None

        return IncomingMessage(
            adapter=self.adapterName,
            channel="telegram",
            sender_id=str(firstMessage.chat.id),
            text=text,
            attachments=attachments,
            external_message_id=str(firstMessage.message_id),
            metadata={
                "attachmentsAmount": len(attachments),
                "telegram": {
                    "mediaGroupId": firstMessage.media_group_id,
                    "messageIds": [message.message_id for message in messages],
                    "chat": firstMessage.chat.model_dump(mode="json"),
                    "from": firstMessage.from_user.model_dump(mode="json") if firstMessage.from_user else None,
                }
            },
        )

    def findMediaGroupText(self, messages: list[Message]) -> str:
        for message in messages:
            text = message.text or message.caption
            if text:
                return text

        return ""

    async def messageToIncoming(self, message: Message) -> IncomingMessage | None:
        text = message.text or message.caption or ""
        attachments = await self.extractAttachments(message)

        if not text and not attachments:
            return None

        return IncomingMessage(
            adapter=self.adapterName,
            channel="telegram",
            sender_id=str(message.chat.id),
            text=text,
            attachments=attachments,
            external_message_id=str(message.message_id),
            metadata={
                "telegram": {
                    "messageId": message.message_id,
                    "chat": message.chat.model_dump(mode="json"),
                    "from": message.from_user.model_dump(mode="json") if message.from_user else None,
                }
            },
        )

    async def extractAttachments(self, message: Message) -> list[MessageFile]:
        attachments: list[MessageFile] = []

        if message.photo:
            photo = message.photo[-1]
            attachments.append(await self.downloadPhoto(photo))

        if message.document:
            attachments.append(await self.downloadDocument(message.document))

        return attachments

    async def downloadPhoto(self, photo: PhotoSize) -> MessageFile:
        content = await self.downloadTelegramFile(photo.file_id)
        return MessageFile(
            file_name=f"{photo.file_unique_id}.jpg",
            mime_type="image/jpeg",
            content_base64=base64.b64encode(content).decode("ascii"),
        )

    async def downloadDocument(self, document: Document) -> MessageFile:
        content = await self.downloadTelegramFile(document.file_id)
        return MessageFile(
            file_name=document.file_name or f"{document.file_unique_id}",
            mime_type=document.mime_type or "application/octet-stream",
            content_base64=base64.b64encode(content).decode("ascii"),
        )

    async def downloadTelegramFile(self, fileId: str) -> bytes:
        telegramFile = await self.client.bot.get_file(fileId)
        if telegramFile.file_path is None:
            raise RuntimeError("Telegram не вернул путь к файлу")

        destination = BytesIO()
        await self.client.bot.download_file(telegramFile.file_path, destination=destination)
        return destination.getvalue()

    def callbackToIncoming(self, callback_query: CallbackQuery) -> IncomingMessage | None:
        if callback_query.data is None or callback_query.message is None:
            return None

        message = callback_query.message
        chat = getattr(message, "chat", None)
        if chat is None:
            return None

        return IncomingMessage(
            adapter=self.adapterName,
            channel="telegram",
            sender_id=str(chat.id),
            text=callback_query.data,
            external_message_id=callback_query.id,
            metadata={
                "telegram": {
                    "callbackQueryId": callback_query.id,
                    "callbackData": callback_query.data,
                    "chat": chat.model_dump(mode="json"),
                    "from": callback_query.from_user.model_dump(mode="json"),
                }
            },
        )


TelegramLongPoll = NewLongPoll
