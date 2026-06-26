import re
from dataclasses import dataclass
from collections.abc import Callable
from typing import Any

from SMK_ADAPTERS.common.models import IncomingMessage


@dataclass(frozen=True, slots=True)
class TriggerUser:
    name: str
    user_id: str
    link: str


USER_MACROS = {
    "{getName()}": "name",
    "{getId()}": "user_id",
    "{getLink()}": "link",
}
EXPLICIT_USER_MACRO_PATTERN = re.compile(r"\{(getName|getId|getLink)\(([A-Za-z]+):([^{}()]+)\)\}")
MacroResolver = Callable[[str, str], TriggerUser | None]


def replaceUserMacros(
    text: str,
    user: TriggerUser | None,
    resolver: MacroResolver | None = None,
) -> str:
    if not text:
        return text

    result = text
    if user is not None:
        for macro, fieldName in USER_MACROS.items():
            result = result.replace(macro, getattr(user, fieldName))

    if resolver is None:
        return result

    return EXPLICIT_USER_MACRO_PATTERN.sub(lambda match: replaceExplicitUserMacro(match, resolver), result)


def replaceExplicitUserMacro(match: re.Match[str], resolver: MacroResolver) -> str:
    methodName = match.group(1)
    platform = match.group(2).upper()
    userId = match.group(3).strip()
    user = resolver(platform, userId) or buildFallbackExplicitUser(platform, userId)
    if user is None:
        return match.group(0)

    if methodName == "getName":
        return user.name
    if methodName == "getId":
        return user.user_id
    if methodName == "getLink":
        return user.link

    return match.group(0)


def buildFallbackExplicitUser(platform: str, userId: str) -> TriggerUser:
    return TriggerUser(
        name=userId,
        user_id=userId,
        link=buildFallbackExplicitUserLink(platform, userId),
    )


def buildFallbackExplicitUserLink(platform: str, userId: str) -> str:
    if platform == "VK":
        if userId.isdigit():
            return f"https://vk.com/id{userId}"
        return f"https://vk.com/{userId}"

    if platform == "TG":
        if userId.isdigit():
            return f"tg://user?id={userId}"
        if isTelegramUsername(userId):
            return f"https://t.me/{userId}"

    return userId


def isTelegramUsername(value: str) -> bool:
    return re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{4,31}", value) is not None


def buildTelegramTriggerUser(message: IncomingMessage) -> TriggerUser:
    telegram = dict(message.metadata.get("telegram") or {})
    userPayload = findTelegramUserPayload(telegram)
    userId = str(userPayload.get("id") or message.sender_id)
    username = str(userPayload.get("username") or "").strip()
    name = makeTelegramUserName(userPayload, username, userId)
    link = f"https://t.me/{username}" if username else f"tg://user?id={userId}"

    return TriggerUser(name=name, user_id=userId, link=link)


def findTelegramUserPayload(telegram: dict[str, Any]) -> dict[str, Any]:
    userPayload = telegram.get("from")
    if isinstance(userPayload, dict):
        return userPayload

    chatPayload = telegram.get("chat")
    if isinstance(chatPayload, dict):
        return chatPayload

    return {}


def makeTelegramUserName(userPayload: dict[str, Any], username: str, userId: str) -> str:
    firstName = str(userPayload.get("first_name") or "").strip()
    lastName = str(userPayload.get("last_name") or "").strip()
    title = str(userPayload.get("title") or "").strip()
    fullName = " ".join(item for item in [firstName, lastName] if item)

    return fullName or title or username or userId


def buildVkTriggerUser(userId: str, profile: dict[str, Any] | None = None) -> TriggerUser:
    profile = profile or {}
    normalizedUserId = str(profile.get("id") or userId)
    firstName = str(profile.get("first_name") or "").strip()
    lastName = str(profile.get("last_name") or "").strip()
    name = " ".join(item for item in [firstName, lastName] if item) or normalizedUserId
    domain = str(profile.get("domain") or profile.get("screen_name") or "").strip()
    link = f"https://vk.com/{domain}" if domain else f"https://vk.com/id{normalizedUserId}"

    return TriggerUser(name=name, user_id=normalizedUserId, link=link)
