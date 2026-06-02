import logging
import time
from collections.abc import Callable

from SMK_ADAPTERS.common.models import IncomingMessage
from SMK_ADAPTERS.telegram_admin_adapter.client import TelegramBotClient


LOGGER = logging.getLogger(__name__)


class NewLongPoll:
    def __init__(
        self,
        client: TelegramBotClient,
        adapter_name: str,
        poll_timeout_seconds: int,
        retry_delay_seconds: float,
    ) -> None:
        self._client = client
        self._adapter_name = adapter_name
        self._poll_timeout_seconds = poll_timeout_seconds
        self._retry_delay_seconds = retry_delay_seconds
        self._offset: int | None = None

    def listen(self, handler: Callable[[IncomingMessage], None]) -> None:
        while True:
            try:
                for update in self._client.getUpdates(self._offset, self._poll_timeout_seconds):
                    message = self.toMessage(update)
                    if message is not None:
                        handler(message)
                    self._offset = int(update["update_id"]) + 1
            except RuntimeError as exc:
                LOGGER.warning("%s. Следующая попытка через %s сек.", exc, self._retry_delay_seconds)
                time.sleep(self._retry_delay_seconds)
            except Exception:
                LOGGER.exception("Итерация долгого опроса Telegram завершилась ошибкой")
                time.sleep(self._retry_delay_seconds)

    def toMessage(self, update: dict) -> IncomingMessage | None:
        callback_query = update.get("callback_query")
        if callback_query:
            return self.callbackToMessage(update, callback_query)

        message = update.get("message") or {}
        text = message.get("text")
        chat = message.get("chat") or {}
        chat_id = chat.get("id")

        if text is None or chat_id is None:
            return None

        return IncomingMessage(
            adapter=self._adapter_name,
            channel="telegram",
            sender_id=str(chat_id),
            text=str(text),
            external_message_id=str(message.get("message_id")) if message.get("message_id") is not None else None,
            metadata={
                "telegram": {
                    "updateId": update.get("update_id"),
                    "chat": chat,
                    "from": message.get("from"),
                }
            },
        )

    def callbackToMessage(self, update: dict, callback_query: dict) -> IncomingMessage | None:
        data = callback_query.get("data")
        message = callback_query.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")

        if data is None or chat_id is None:
            return None

        callback_query_id = callback_query.get("id")
        if callback_query_id is not None:
            self._client.answerCallbackQuery(str(callback_query_id))

        return IncomingMessage(
            adapter=self._adapter_name,
            channel="telegram",
            sender_id=str(chat_id),
            text=str(data),
            external_message_id=str(callback_query_id) if callback_query_id is not None else None,
            metadata={
                "telegram": {
                    "updateId": update.get("update_id"),
                    "callbackQuery": callback_query,
                }
            },
        )


TelegramLongPoll = NewLongPoll
