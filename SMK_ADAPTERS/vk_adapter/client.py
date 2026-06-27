import hashlib
import logging
import os
import tempfile
import threading
from collections import OrderedDict
from typing import Any

from vk_api import VkApi, VkUpload
from vk_api.keyboard import VkKeyboard, VkKeyboardColor
from vk_api.utils import get_random_id

from SMK_ADAPTERS.common.constants import VK_BUTTON_COLOR_TO_STYLE
from SMK_ADAPTERS.common.models import KeyboardElement


LOGGER = logging.getLogger(__name__)
VK_BUTTON_LABEL_MAX_LENGTH = 40
PHOTO_ATTACHMENT_CACHE_MAX_ITEMS = 256
USER_PROFILE_CACHE_MAX_ITEMS = 1024


class VkApiError(RuntimeError):
    def __init__(self, message: str, error_code: int | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code


class KeyboardConfigurator:
    def makeKeyboard(
        self,
        inline_elements: list[list[KeyboardElement]] | None = None,
        reply_elements: list[list[KeyboardElement]] | None = None,
    ) -> VkKeyboard | None:
        if inline_elements:
            return self.makeKeyboardFromRows(inline_elements, inline=True)

        if reply_elements:
            return self.makeKeyboardFromRows(reply_elements, inline=False)

        return None

    def makeKeyboardFromRows(self, rows: list[list[KeyboardElement]], inline: bool) -> VkKeyboard | None:
        keyboard = VkKeyboard(inline=inline)
        hasButtons = False

        for rowIndex, row in enumerate(rows):
            if rowIndex > 0 and hasButtons:
                keyboard.add_line()

            for element in row:
                if not element.text:
                    continue

                self.addKeyboardButton(keyboard, element)
                hasButtons = True

        if not hasButtons:
            return None

        return keyboard

    def addKeyboardButton(self, keyboard: VkKeyboard, element: KeyboardElement) -> None:
        label = self.makeButtonLabel(element.text)
        if element.link:
            keyboard.add_openlink_button(label=label, link=element.link)
            return

        keyboard.add_button(label, color=self.getButtonColor(element))

    def makeButtonLabel(self, text: str) -> str:
        if len(text) <= VK_BUTTON_LABEL_MAX_LENGTH:
            return text

        return text[:VK_BUTTON_LABEL_MAX_LENGTH]

    def getButtonColor(self, element: KeyboardElement) -> VkKeyboardColor:
        style = VK_BUTTON_COLOR_TO_STYLE.get((element.color or "").strip().lower())
        if style == "positive":
            return VkKeyboardColor.POSITIVE
        if style == "primary":
            return VkKeyboardColor.PRIMARY

        return VkKeyboardColor.SECONDARY


class VkBotClient(KeyboardConfigurator):
    def __init__(self, token: str) -> None:
        self.authorize = VkApi(token=token)
        self.session = self.authorize.get_api()
        self.upload = VkUpload(self.authorize)
        self._photo_attachment_cache: OrderedDict[str, str] = OrderedDict()
        self._photo_attachment_cache_lock = threading.Lock()
        self._user_profile_cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._user_profile_cache_lock = threading.Lock()

    def sendMessage(
        self,
        chat_id: str,
        text: str,
        inline_elements: list[list[KeyboardElement]] | None = None,
        reply_elements: list[list[KeyboardElement]] | None = None,
    ) -> None:
        keyboard = self.makeKeyboard(inline_elements, reply_elements)
        payload: dict[str, Any] = {
            "user_id": chat_id,
            "message": text,
            "random_id": get_random_id(),
        }
        if keyboard is not None:
            payload["keyboard"] = keyboard.get_keyboard()

        self.request("messages.send", payload)

    def sendImageWithText(
        self,
        chat_id: str,
        content: bytes,
        file_name: str,
        text: str,
        inline_elements: list[list[KeyboardElement]] | None = None,
        reply_elements: list[list[KeyboardElement]] | None = None,
    ) -> None:
        self.sendImagesWithText(chat_id, [(content, file_name)], text, inline_elements, reply_elements)

    def sendImagesWithText(
        self,
        chat_id: str,
        files: list[tuple[bytes, str]],
        text: str,
        inline_elements: list[list[KeyboardElement]] | None = None,
        reply_elements: list[list[KeyboardElement]] | None = None,
    ) -> None:
        attachments = self.uploadMessagePhotos(chat_id, files)
        keyboard = self.makeKeyboard(inline_elements, reply_elements)
        payload: dict[str, Any] = {
            "user_id": chat_id,
            "message": text,
            "random_id": get_random_id(),
            "attachment": ",".join(attachments),
        }
        if keyboard is not None:
            payload["keyboard"] = keyboard.get_keyboard()

        self.request("messages.send", payload)

    def uploadMessagePhotos(self, chat_id: str, files: list[tuple[bytes, str]]) -> list[str]:
        attachments: list[str | None] = [None] * len(files)
        filesForUpload: list[tuple[int, str, str]] = []
        paths: list[str] = []

        for index, (content, fileName) in enumerate(files):
            cacheKey = self.makePhotoAttachmentCacheKey(content)
            cachedAttachment = self.getCachedPhotoAttachment(cacheKey)
            if cachedAttachment is not None:
                LOGGER.debug("Фотография VK взята из кэша вложений: fileName=%s", fileName)
                attachments[index] = cachedAttachment
                continue

            path = self.writeTempFile(content, fileName)
            paths.append(path)
            filesForUpload.append((index, cacheKey, path))

        try:
            if filesForUpload:
                try:
                    uploadedPhotos = self.upload.photo_messages(
                        photos=[path for _, _, path in filesForUpload],
                        peer_id=int(chat_id),
                    )
                except Exception as exc:
                    raise VkApiError(
                        f"Запрос к VK API завершился ошибкой при загрузке фотографий: {exc}",
                        error_code=self.extractErrorCode(exc),
                    ) from exc
                if len(uploadedPhotos) != len(filesForUpload):
                    raise VkApiError(
                        f"VK вернул некорректное количество загруженных фотографий: "
                        f"ожидалось {len(filesForUpload)}, получено {len(uploadedPhotos)}"
                    )

                for (index, cacheKey, _), photo in zip(filesForUpload, uploadedPhotos):
                    attachment = self.makePhotoAttachment(photo)
                    attachments[index] = attachment
                    self.cachePhotoAttachment(cacheKey, attachment)

            return [attachment for attachment in attachments if attachment is not None]
        finally:
            for path in paths:
                try:
                    os.remove(path)
                except OSError:
                    LOGGER.debug("Не удалось удалить временный файл VK", exc_info=True)

    def makePhotoAttachmentCacheKey(self, content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    def getCachedPhotoAttachment(self, cacheKey: str) -> str | None:
        with self._photo_attachment_cache_lock:
            attachment = self._photo_attachment_cache.get(cacheKey)
            if attachment is None:
                return None

            self._photo_attachment_cache.move_to_end(cacheKey)
            return attachment

    def cachePhotoAttachment(self, cacheKey: str, attachment: str) -> None:
        with self._photo_attachment_cache_lock:
            self._photo_attachment_cache[cacheKey] = attachment
            self._photo_attachment_cache.move_to_end(cacheKey)

            while len(self._photo_attachment_cache) > PHOTO_ATTACHMENT_CACHE_MAX_ITEMS:
                self._photo_attachment_cache.popitem(last=False)

    def makePhotoAttachment(self, photo: dict[str, Any]) -> str:
        accessKey = photo.get("access_key")
        if accessKey:
            return f"photo{photo['owner_id']}_{photo['id']}_{accessKey}"

        return f"photo{photo['owner_id']}_{photo['id']}"

    def writeTempFile(self, content: bytes, fileName: str) -> str:
        _, extension = os.path.splitext(fileName)
        file = tempfile.NamedTemporaryFile(delete=False, suffix=extension or ".bin")
        try:
            file.write(content)
            return file.name
        finally:
            file.close()

    def getUserProfile(self, user_id: str) -> dict[str, Any]:
        cachedProfile = self.getCachedUserProfile(user_id)
        if cachedProfile is not None:
            return cachedProfile

        profiles = self.request(
            "users.get",
            {
                "user_ids": user_id,
                "fields": "domain,screen_name",
            },
        )
        if not profiles:
            return {}

        profile = dict(profiles[0])
        self.cacheUserProfile(user_id, profile)
        return profile

    def getCachedUserProfile(self, user_id: str) -> dict[str, Any] | None:
        with self._user_profile_cache_lock:
            profile = self._user_profile_cache.get(user_id)
            if profile is None:
                return None

            self._user_profile_cache.move_to_end(user_id)
            return profile

    def cacheUserProfile(self, user_id: str, profile: dict[str, Any]) -> None:
        with self._user_profile_cache_lock:
            self._user_profile_cache[user_id] = profile
            self._user_profile_cache.move_to_end(user_id)

            while len(self._user_profile_cache) > USER_PROFILE_CACHE_MAX_ITEMS:
                self._user_profile_cache.popitem(last=False)

    def extractErrorCode(self, exc: Exception) -> int | None:
        return getattr(exc, "code", None) or getattr(exc, "error_code", None)

    def request(self, method: str, payload: dict[str, Any]) -> Any:
        try:
            return self.authorize.method(method, payload)
        except Exception as exc:
            errorCode = self.extractErrorCode(exc)
            raise VkApiError(f"Запрос к VK API завершился ошибкой: {exc}", error_code=errorCode) from exc


class MessageService(VkBotClient):
    pass
