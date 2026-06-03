import json
import logging
import threading
import time
from collections import OrderedDict
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from SMK_ADAPTERS.common.config import ApiConfig
from SMK_ADAPTERS.common.models import BackendResponse, IncomingMessage


LOGGER = logging.getLogger(__name__)
FILE_CACHE_TTL_SECONDS = 600
FILE_CACHE_MAX_ITEMS = 128
API_REQUEST_RETRY_COUNT = 3
API_REQUEST_RETRY_DELAY_SECONDS = 2


class SmcApiClient:
    def __init__(self, config: ApiConfig) -> None:
        self._config = config
        self._file_cache: OrderedDict[str, tuple[float, bytes]] = OrderedDict()
        self._file_cache_lock = threading.Lock()

    def sendAdminMessage(self, message: IncomingMessage) -> BackendResponse:
        payload = self.postJson(self._config.admin_endpoint, message.toApiPayload(self._config.platform))
        return BackendResponse.fromPayload(payload, fallback_recipient_id=message.sender_id)

    def sendUserMessage(self, message: IncomingMessage) -> BackendResponse:
        payload = self.postJson(self._config.user_endpoint, message.toApiPayload(self._config.platform))
        return BackendResponse.fromPayload(payload, fallback_recipient_id=message.sender_id)

    def getFile(self, fileId: str) -> bytes:
        cached = self.getCachedFile(fileId)
        if cached is not None:
            LOGGER.debug("Файл smc.api взят из кэша: fileId=%s", fileId)
            return cached

        content = self.getBytes(f"/api/v1/files/{fileId}")
        self.cacheFile(fileId, content)
        return content

    def getCachedFile(self, fileId: str) -> bytes | None:
        now = time.monotonic()
        with self._file_cache_lock:
            cached = self._file_cache.get(fileId)
            if cached is None:
                return None

            cached_at, content = cached
            if now - cached_at > FILE_CACHE_TTL_SECONDS:
                self._file_cache.pop(fileId, None)
                return None

            self._file_cache.move_to_end(fileId)
            return content

    def cacheFile(self, fileId: str, content: bytes) -> None:
        with self._file_cache_lock:
            self._file_cache[fileId] = (time.monotonic(), content)
            self._file_cache.move_to_end(fileId)

            while len(self._file_cache) > FILE_CACHE_MAX_ITEMS:
                self._file_cache.popitem(last=False)

    def postJson(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = self.buildUrl(endpoint)
        LOGGER.info("Отправка запроса в smc.api: %s", url)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "api-key": self._config.api_key,
            },
            method="POST",
        )

        for attempt in range(1, API_REQUEST_RETRY_COUNT + 1):
            try:
                with urlopen(request, timeout=self._config.timeout_seconds) as response:
                    response_body = response.read().decode("utf-8")
                    if not response_body:
                        return {}
                    return json.loads(response_body)
            except HTTPError as exc:
                details = exc.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"Запрос к smc.api завершился ошибкой со статусом {exc.code}: {details}") from exc
            except URLError as exc:
                if attempt < API_REQUEST_RETRY_COUNT:
                    LOGGER.warning(
                        "Запрос к smc.api завершился сетевой ошибкой: %s. Следующая попытка через %s сек.",
                        exc.reason,
                        API_REQUEST_RETRY_DELAY_SECONDS,
                    )
                    time.sleep(API_REQUEST_RETRY_DELAY_SECONDS)
                    continue

                raise RuntimeError(f"Запрос к smc.api завершился ошибкой: {exc.reason}") from exc
            except json.JSONDecodeError as exc:
                raise RuntimeError("smc.api вернул некорректный JSON") from exc

        raise RuntimeError("Запрос к smc.api завершился ошибкой")

    def getBytes(self, endpoint: str) -> bytes:
        url = self.buildUrl(endpoint)
        LOGGER.info("Получение файла из smc.api: %s", url)
        request = Request(
            url,
            headers={
                "Accept": "*/*",
                "api-key": self._config.api_key,
            },
            method="GET",
        )

        try:
            with urlopen(request, timeout=self._config.timeout_seconds) as response:
                return response.read()
        except HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Запрос файла к smc.api завершился ошибкой со статусом {exc.code}: {details}") from exc
        except URLError as exc:
            raise RuntimeError(f"Запрос файла к smc.api завершился ошибкой: {exc.reason}") from exc

    def buildUrl(self, endpoint: str) -> str:
        if endpoint.startswith("http://") or endpoint.startswith("https://"):
            return endpoint
        return f"{self._config.base_url}/{endpoint.lstrip('/')}"
