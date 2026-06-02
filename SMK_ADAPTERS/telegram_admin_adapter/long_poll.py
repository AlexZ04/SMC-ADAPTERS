import asyncio
import logging
from collections.abc import Callable

from aiogram import Dispatcher
from aiogram.types import CallbackQuery, Message

from SMK_ADAPTERS.common.models import IncomingMessage
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
                )
            except RuntimeError as exc:
                LOGGER.warning("%s. Следующая попытка через %s сек.", exc, self.retryDelaySeconds)
                await asyncio.sleep(self.retryDelaySeconds)
            except Exception:
                LOGGER.exception("Долгий опрос Telegram завершился ошибкой")
                await asyncio.sleep(self.retryDelaySeconds)

    def registerHandlers(self, handler: Callable[[IncomingMessage], None]) -> None:
        @self.dispatcher.message()
        async def onMessage(message: Message) -> None:
            incomingMessage = self.messageToIncoming(message)
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

    def messageToIncoming(self, message: Message) -> IncomingMessage | None:
        if message.text is None or message.chat.id is None:
            return None

        return IncomingMessage(
            adapter=self.adapterName,
            channel="telegram",
            sender_id=str(message.chat.id),
            text=message.text,
            external_message_id=str(message.message_id),
            metadata={
                "telegram": {
                    "messageId": message.message_id,
                    "chat": message.chat.model_dump(mode="json"),
                    "from": message.from_user.model_dump(mode="json") if message.from_user else None,
                }
            },
        )

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
