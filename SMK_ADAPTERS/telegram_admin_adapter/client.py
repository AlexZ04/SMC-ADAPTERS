import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from SMK_ADAPTERS.common.constants import (
    KEYBOARD_BUTTON_TYPE_LINK,
    TELEGRAM_BUTTON_COLOR_TO_STYLE,
    TELEGRAM_FIELD_CALLBACK_DATA,
    TELEGRAM_FIELD_INLINE_KEYBOARD,
    TELEGRAM_FIELD_KEYBOARD,
    TELEGRAM_FIELD_ONE_TIME_KEYBOARD,
    TELEGRAM_FIELD_REPLY_MARKUP,
    TELEGRAM_FIELD_RESIZE_KEYBOARD,
    TELEGRAM_FIELD_STYLE,
    TELEGRAM_FIELD_TEXT,
    TELEGRAM_FIELD_URL,
)
from SMK_ADAPTERS.common.models import KeyboardElement


class TelegramApiError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class TelegramBotClient:
    def __init__(self, token: str, timeout_seconds: float = 10) -> None:
        self._base_url = f"https://api.telegram.org/bot{token}"
        self._timeout_seconds = timeout_seconds

    def getUpdates(self, offset: int | None, timeout_seconds: int) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "timeout": timeout_seconds,
            "allowed_updates": ["message", "callback_query"],
        }
        if offset is not None:
            payload["offset"] = offset

        response = self.request("getUpdates", payload)
        return list(response.get("result") or [])

    def sendMessage(
        self,
        chat_id: str,
        text: str,
        inline_elements: list[list[KeyboardElement]] | None = None,
        reply_elements: list[list[KeyboardElement]] | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
        }

        inline_markup = self.makeInlineMarkup(inline_elements or [])
        reply_markup = self.makeReplyMarkup(reply_elements or [])

        if inline_markup:
            payload[TELEGRAM_FIELD_REPLY_MARKUP] = inline_markup
        elif reply_markup:
            payload[TELEGRAM_FIELD_REPLY_MARKUP] = reply_markup

        self.request("sendMessage", payload)

    def answerCallbackQuery(self, callback_query_id: str) -> None:
        self.request(
            "answerCallbackQuery",
            {
                "callback_query_id": callback_query_id,
            },
        )

    def makeInlineMarkup(self, rows: list[list[KeyboardElement]]) -> dict[str, Any] | None:
        keyboard: list[list[dict[str, str]]] = []

        for row in rows:
            buttons = []
            for element in row:
                button = {TELEGRAM_FIELD_TEXT: element.text}
                style = self.makeButtonStyle(element)
                if style is not None:
                    button[TELEGRAM_FIELD_STYLE] = style

                if element.type == KEYBOARD_BUTTON_TYPE_LINK and element.link:
                    button[TELEGRAM_FIELD_URL] = element.link
                else:
                    button[TELEGRAM_FIELD_CALLBACK_DATA] = element.text

                buttons.append(button)

            if buttons:
                keyboard.append(buttons)

        if not keyboard:
            return None

        return {TELEGRAM_FIELD_INLINE_KEYBOARD: keyboard}

    def makeReplyMarkup(self, rows: list[list[KeyboardElement]]) -> dict[str, Any] | None:
        keyboard = [
            [self.makeReplyButton(element) for element in row if element.text]
            for row in rows
        ]
        keyboard = [row for row in keyboard if row]

        if not keyboard:
            return None

        return {
            TELEGRAM_FIELD_KEYBOARD: keyboard,
            TELEGRAM_FIELD_RESIZE_KEYBOARD: True,
            TELEGRAM_FIELD_ONE_TIME_KEYBOARD: False,
        }

    def makeReplyButton(self, element: KeyboardElement) -> dict[str, str]:
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

    def request(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            f"{self._base_url}/{method}",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=self._timeout_seconds + float(payload.get("timeout", 0))) as response:
                response_body = response.read().decode("utf-8")
                data = json.loads(response_body)
        except HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise TelegramApiError(
                f"Запрос к Telegram API завершился ошибкой со статусом {exc.code}: {details}",
                status_code=exc.code,
            ) from exc
        except URLError as exc:
            raise RuntimeError(f"Запрос к Telegram API завершился ошибкой: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError("Telegram API вернул некорректный JSON") from exc

        if not data.get("ok"):
            raise TelegramApiError(f"Telegram API вернул ошибку: {data}")

        return data
