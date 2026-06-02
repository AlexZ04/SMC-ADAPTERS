from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class KeyboardElement:
    type: str
    text: str
    link: str | None = None
    color: str | None = None
    text_color: str | None = None

    @classmethod
    def fromDict(cls, payload: dict[str, Any]) -> "KeyboardElement":
        return cls(
            type=str(payload.get("type") or "BUTTON"),
            text=str(payload.get("text") or ""),
            link=str(payload.get("link")) if payload.get("link") is not None else None,
            color=str(payload.get("color")) if payload.get("color") is not None else None,
            text_color=str(payload.get("textColor")) if payload.get("textColor") is not None else None,
        )

    def toDict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "link": self.link,
            "text": self.text,
            "color": self.color,
            "textColor": self.text_color,
        }


@dataclass(frozen=True, slots=True)
class IncomingMessage:
    adapter: str
    channel: str
    sender_id: str
    text: str
    external_message_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def toApiPayload(self, platform: str) -> dict[str, Any]:
        return {
            "message": self.text,
            "platform": platform,
            "userIdOnPlatform": self.sender_id,
            "attachmentsAmount": int(self.metadata.get("attachmentsAmount") or 0),
        }


@dataclass(frozen=True, slots=True)
class BackendResponse:
    recipient_id: str | None
    text: str
    preview_messages: list[str] = field(default_factory=list)
    inline_elements: list[list[KeyboardElement]] = field(default_factory=list)
    reply_elements: list[list[KeyboardElement]] = field(default_factory=list)
    raw_payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def fromPayload(cls, payload: dict[str, Any], fallback_recipient_id: str | None = None) -> "BackendResponse":
        response_to_user = payload.get("responseToUser") or {}
        recipient_id = (
            payload.get("recipientId")
            or payload.get("recipient_id")
            or payload.get("userIdOnPlatform")
            or payload.get("chatId")
            or payload.get("chat_id")
            or fallback_recipient_id
        )
        text = (
            response_to_user.get("responseText")
            or payload.get("responseText")
            or payload.get("text")
            or payload.get("message")
            or ""
        )
        preview_messages = parsePreviewMessages(
            response_to_user.get("previewMessages") or payload.get("previewMessages") or []
        )
        inline_elements = parseKeyboard(response_to_user.get("inlineElements") or payload.get("inlineElements") or [])
        reply_elements = parseKeyboard(response_to_user.get("replyElements") or payload.get("replyElements") or [])

        return cls(
            recipient_id=str(recipient_id) if recipient_id is not None else None,
            text=str(text),
            preview_messages=preview_messages,
            inline_elements=inline_elements,
            reply_elements=reply_elements,
            raw_payload=payload,
        )


@dataclass(frozen=True, slots=True)
class QueueMessage:
    id: str
    recipient_id: str
    text: str
    adapter: str
    preview_messages: list[str] = field(default_factory=list)
    inline_elements: list[list[KeyboardElement]] = field(default_factory=list)
    reply_elements: list[list[KeyboardElement]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def toDict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "recipientId": self.recipient_id,
            "text": self.text,
            "adapter": self.adapter,
            "previewMessages": self.preview_messages,
            "inlineElements": keyboardToDict(self.inline_elements),
            "replyElements": keyboardToDict(self.reply_elements),
            "metadata": self.metadata,
        }

    @classmethod
    def create(
        cls,
        recipient_id: str,
        text: str,
        adapter: str,
        preview_messages: list[str] | None = None,
        inline_elements: list[list[KeyboardElement]] | None = None,
        reply_elements: list[list[KeyboardElement]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "QueueMessage":
        return cls(
            id=str(uuid4()),
            recipient_id=recipient_id,
            text=text,
            adapter=adapter,
            preview_messages=preview_messages or [],
            inline_elements=inline_elements or [],
            reply_elements=reply_elements or [],
            metadata=metadata or {},
        )

    @classmethod
    def fromDict(cls, payload: dict[str, Any], default_adapter: str) -> "QueueMessage":
        recipient_id = payload.get("recipientId") or payload.get("recipient_id") or payload.get("chatId") or payload.get("chat_id")
        text = payload.get("text") or payload.get("message")

        if recipient_id is None:
            raise ValueError("В сообщении очереди обязателен идентификатор получателя")
        if text is None:
            raise ValueError("В сообщении очереди обязателен текст")

        return cls(
            id=str(payload.get("id") or uuid4()),
            recipient_id=str(recipient_id),
            text=str(text),
            adapter=str(payload.get("adapter") or default_adapter),
            preview_messages=parsePreviewMessages(payload.get("previewMessages") or payload.get("preview_messages") or []),
            inline_elements=parseKeyboard(payload.get("inlineElements") or payload.get("inline_elements") or []),
            reply_elements=parseKeyboard(payload.get("replyElements") or payload.get("reply_elements") or []),
            metadata=dict(payload.get("metadata") or {}),
        )


def parseKeyboard(rows: list) -> list[list[KeyboardElement]]:
    result: list[list[KeyboardElement]] = []

    for row in rows:
        if not isinstance(row, list):
            continue

        parsed_row = [
            KeyboardElement.fromDict(element)
            for element in row
            if isinstance(element, dict) and element.get("text")
        ]
        if parsed_row:
            result.append(parsed_row)

    return result


def parsePreviewMessages(messages: list) -> list[str]:
    result: list[str] = []

    for message in messages:
        text = parsePreviewMessageText(message)
        if text:
            result.append(text)

    return result


def parsePreviewMessageText(message: Any) -> str:
    if isinstance(message, str):
        return message

    if not isinstance(message, dict):
        return ""

    text = (
        message.get("responseText")
        or message.get("text")
        or message.get("message")
        or message.get("previewText")
        or ""
    )
    return str(text)


def keyboardToDict(rows: list[list[KeyboardElement]]) -> list[list[dict[str, Any]]]:
    return [[element.toDict() for element in row] for row in rows]
