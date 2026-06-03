import json
import logging
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from SMK_ADAPTERS.common.config import ApiConfig
from SMK_ADAPTERS.common.models import BackendResponse, IncomingMessage


LOGGER = logging.getLogger(__name__)


class SmcApiClient:
    def __init__(self, config: ApiConfig) -> None:
        self._config = config

    def sendAdminMessage(self, message: IncomingMessage) -> BackendResponse:
        payload = self.postJson(self._config.admin_endpoint, message.toApiPayload(self._config.platform))
        return BackendResponse.fromPayload(payload, fallback_recipient_id=message.sender_id)

    def getFile(self, fileId: str) -> bytes:
        return self.getBytes(f"/api/v1/files/{fileId}")

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
            raise RuntimeError(f"Запрос к smc.api завершился ошибкой: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError("smc.api вернул некорректный JSON") from exc

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
