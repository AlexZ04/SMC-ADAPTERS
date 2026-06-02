from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from SMK_ADAPTERS.common.constants import (
    KEYBOARD_BUTTON_TYPE_LINK,
    TELEGRAM_BUTTON_COLOR_TO_STYLE,
    TELEGRAM_FIELD_CALLBACK_DATA,
    TELEGRAM_FIELD_INLINE_KEYBOARD,
    TELEGRAM_FIELD_KEYBOARD,
    TELEGRAM_FIELD_ONE_TIME_KEYBOARD,
    TELEGRAM_FIELD_RESIZE_KEYBOARD,
    TELEGRAM_FIELD_STYLE,
    TELEGRAM_FIELD_TEXT,
    TELEGRAM_FIELD_URL,
)
from SMK_ADAPTERS.common.models import KeyboardElement
from SMK_ADAPTERS.telegram_admin_adapter.async_runtime import TelegramAsyncRuntime


class TelegramApiError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class TelegramBotClient:
    def __init__(self, token: str, runtime: TelegramAsyncRuntime, timeout_seconds: float = 10) -> None:
        self.bot = Bot(token=token)
        self.runtime = runtime
        self.timeoutSeconds = timeout_seconds

    def sendMessage(
        self,
        chat_id: str,
        text: str,
        inline_elements: list[list[KeyboardElement]] | None = None,
        reply_elements: list[list[KeyboardElement]] | None = None,
    ) -> None:
        self.runtime.run(self.sendMessageAsync(chat_id, text, inline_elements, reply_elements))

    async def sendMessageAsync(
        self,
        chat_id: str,
        text: str,
        inline_elements: list[list[KeyboardElement]] | None = None,
        reply_elements: list[list[KeyboardElement]] | None = None,
    ) -> None:
        inline_markup = self.makeInlineMarkup(inline_elements or [])
        reply_markup = self.makeReplyMarkup(reply_elements or [])
        markup = inline_markup or reply_markup

        try:
            await self.bot.send_message(chat_id=chat_id, text=text, reply_markup=markup)
        except TelegramBadRequest as exc:
            raise TelegramApiError(f"Telegram отклонил сообщение: {exc}", status_code=400) from exc
        except TelegramAPIError as exc:
            raise TelegramApiError(f"Запрос к Telegram API завершился ошибкой: {exc}") from exc

    async def answerCallbackQueryAsync(self, callback_query_id: str) -> None:
        try:
            await self.bot.answer_callback_query(callback_query_id=callback_query_id)
        except TelegramBadRequest as exc:
            raise TelegramApiError(f"Telegram отклонил callback query: {exc}", status_code=400) from exc
        except TelegramAPIError as exc:
            raise TelegramApiError(f"Запрос к Telegram API завершился ошибкой: {exc}") from exc

    def makeInlineMarkup(self, rows: list[list[KeyboardElement]]) -> InlineKeyboardMarkup | None:
        keyboard = []

        for row in rows:
            buttons = [self.makeInlineButton(element) for element in row if element.text]
            if buttons:
                keyboard.append(buttons)

        if not keyboard:
            return None

        return InlineKeyboardMarkup(**{TELEGRAM_FIELD_INLINE_KEYBOARD: keyboard})

    def makeInlineButton(self, element: KeyboardElement) -> InlineKeyboardButton:
        button = self.makeButtonData(element)

        if element.type == KEYBOARD_BUTTON_TYPE_LINK and element.link:
            button[TELEGRAM_FIELD_URL] = element.link
        else:
            button[TELEGRAM_FIELD_CALLBACK_DATA] = element.text

        return InlineKeyboardButton(**button)

    def makeReplyMarkup(self, rows: list[list[KeyboardElement]]) -> ReplyKeyboardMarkup | None:
        keyboard = [
            [self.makeReplyButton(element) for element in row if element.text]
            for row in rows
        ]
        keyboard = [row for row in keyboard if row]

        if not keyboard:
            return None

        return ReplyKeyboardMarkup(
            **{
                TELEGRAM_FIELD_KEYBOARD: keyboard,
                TELEGRAM_FIELD_RESIZE_KEYBOARD: True,
                TELEGRAM_FIELD_ONE_TIME_KEYBOARD: False,
            }
        )

    def makeReplyButton(self, element: KeyboardElement) -> KeyboardButton:
        return KeyboardButton(**self.makeButtonData(element))

    def makeButtonData(self, element: KeyboardElement) -> dict[str, Any]:
        button = {TELEGRAM_FIELD_TEXT: element.text}
        style = self.makeButtonStyle(element)
        if style is not None:
            button[TELEGRAM_FIELD_STYLE] = style

        return button

    def makeButtonStyle(self, element: KeyboardElement) -> str | None:
        value = (element.color or "").strip().lower()
        if not value:
            return None

        return TELEGRAM_BUTTON_COLOR_TO_STYLE.get(value)
