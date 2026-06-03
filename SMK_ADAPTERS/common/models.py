from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class MessageFile:
    file_name: str
    mime_type: str
    content_base64: str

    def toApiPayload(self) -> dict[str, Any]:
        return {
            "fileName": self.file_name,
            "mimeType": self.mime_type,
            "contentBase64": self.content_base64,
        }


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
class DistributionReceiver:
    platform: str
    role: str
    receiver_id: str
    inline_elements: list[list[KeyboardElement]] = field(default_factory=list)
    reply_elements: list[list[KeyboardElement]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class DistributionMessage:
    text: str
    files_ids: list[str] = field(default_factory=list)
    inline_elements: list[list[KeyboardElement]] = field(default_factory=list)
    receivers: list[DistributionReceiver] = field(default_factory=list)
    send_to_himself: bool = False


@dataclass(frozen=True, slots=True)
class IncomingMessage:
    adapter: str
    channel: str
    sender_id: str
    text: str
    attachments: list[MessageFile] = field(default_factory=list)
    external_message_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def toApiPayload(self, platform: str) -> dict[str, Any]:
        return {
            "message": self.text,
            "platform": platform,
            "userIdOnPlatform": self.sender_id,
            "attachmentsAmount": len(self.attachments),
            "attachments": [attachment.toApiPayload() for attachment in self.attachments],
        }


@dataclass(frozen=True, slots=True)
class BackendResponse:
    recipient_id: str | None
    text: str
    role: str | None = None
    preview_messages: list[str] = field(default_factory=list)
    files_ids: list[str] = field(default_factory=list)
    inline_elements: list[list[KeyboardElement]] = field(default_factory=list)
    reply_elements: list[list[KeyboardElement]] = field(default_factory=list)
    distribution: DistributionMessage | None = None
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
        role = str(payload.get("role")) if payload.get("role") is not None else None
        preview_messages = parsePreviewMessages(
            response_to_user.get("previewMessages") or payload.get("previewMessages") or []
        )
        files_ids = parseFilesIds(
            response_to_user.get("filesIds")
            or payload.get("filesIds")
            or response_to_user.get("previewFiles")
            or payload.get("previewFiles")
            or []
        )
        inline_elements = parseKeyboard(response_to_user.get("inlineElements") or payload.get("inlineElements") or [])
        reply_elements = parseKeyboard(response_to_user.get("replyElements") or payload.get("replyElements") or [])
        distribution = parseDistribution(response_to_user.get("distribution") or response_to_user, role)

        return cls(
            recipient_id=str(recipient_id) if recipient_id is not None else None,
            text=str(text),
            role=role,
            preview_messages=preview_messages,
            files_ids=files_ids,
            inline_elements=inline_elements,
            reply_elements=reply_elements,
            distribution=distribution,
            raw_payload=payload,
        )


@dataclass(frozen=True, slots=True)
class QueueMessage:
    id: str
    recipient_id: str
    text: str
    adapter: str
    preview_messages: list[str] = field(default_factory=list)
    files_ids: list[str] = field(default_factory=list)
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
            "filesIds": self.files_ids,
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
        files_ids: list[str] | None = None,
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
            files_ids=files_ids or [],
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
            files_ids=parseFilesIds(
                payload.get("filesIds")
                or payload.get("files_ids")
                or payload.get("previewFiles")
                or payload.get("preview_files")
                or []
            ),
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


def parseDistribution(payload: Any, fallbackRole: str | None = None) -> DistributionMessage | None:
    if not isinstance(payload, dict):
        return None

    receivers = parseDistributionReceivers(
        payload.get("receivers")
        or payload.get("distributionReceivers")
        or payload.get("recipients")
        or [],
        fallbackRole,
    )
    if not receivers:
        return None

    text = str(
        payload.get("distributionText")
        or payload.get("responseText")
        or payload.get("text")
        or payload.get("message")
        or ""
    )
    if not text:
        return None

    filesIds = parseFilesIds(
        payload.get("distributionFiles")
        or payload.get("filesIds")
        or payload.get("previewFiles")
        or []
    )
    inlineElements = parseKeyboard(payload.get("distributionInlineElements") or payload.get("inlineElements") or [])

    return DistributionMessage(
        text=text,
        files_ids=filesIds,
        inline_elements=inlineElements,
        receivers=receivers,
        send_to_himself=bool(payload.get("sendToHimself")),
    )


def parseDistributionReceivers(receivers: Any, fallbackRole: str | None = None) -> list[DistributionReceiver]:
    if not isinstance(receivers, list):
        return []

    result: list[DistributionReceiver] = []
    for receiver in receivers:
        if not isinstance(receiver, dict):
            continue

        platform = str(receiver.get("platform") or "").upper()
        role = str(
            receiver.get("role")
            or receiver.get("receiverRole")
            or receiver.get("recipientRole")
            or receiver.get("userRole")
            or fallbackRole
            or ""
        ).upper()
        receiversIds = parseReceiversIds(receiver)

        if not platform or not role or not receiversIds:
            continue

        for receiverId in receiversIds:
            result.append(
                DistributionReceiver(
                    platform=platform,
                    role=role,
                    receiver_id=receiverId,
                    inline_elements=parseKeyboard(receiver.get("inlineElements") or []),
                    reply_elements=parseKeyboard(receiver.get("replyElements") or []),
                )
            )

    return result


def parseReceiversIds(receiver: dict[str, Any]) -> list[str]:
    value = (
        receiver.get("receiversId")
        or receiver.get("receiversIds")
        or receiver.get("receiverIds")
        or receiver.get("receiverId")
        or receiver.get("recipientId")
        or receiver.get("userIdOnPlatform")
    )

    if isinstance(value, list):
        return [str(item) for item in value if item is not None and str(item)]

    if value is None:
        return []

    return [str(value)]


def parsePreviewMessages(messages: list) -> list[str]:
    if not isinstance(messages, list):
        return []

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


def parseFilesIds(files: list) -> list[str]:
    if not isinstance(files, list):
        return []

    result: list[str] = []

    for fileId in files:
        if fileId:
            result.append(str(fileId))

    return result


def keyboardToDict(rows: list[list[KeyboardElement]]) -> list[list[dict[str, Any]]]:
    return [[element.toDict() for element in row] for row in rows]
