import os
from dataclasses import dataclass
from dataclasses import replace
from pathlib import Path

from SMK_ADAPTERS.common.config import CommonSettings, PROJECT_ROOT, loadCommonSettings
from SMK_ADAPTERS.common.constants import DEFAULT_ADMIN_ENDPOINT
from SMK_ADAPTERS.telegram_admin_adapter.settings import loadConfigValues


DEFAULT_TOKEN_FILE = PROJECT_ROOT / "SMK_ADAPTERS" / "vk_adapter" / "config" / "secrets" / "vk_bot_token.txt"


@dataclass(frozen=True, slots=True)
class VkSettings:
    token_file: Path
    adapter_role: str


@dataclass(frozen=True, slots=True)
class VkAdapterSettings:
    common: CommonSettings
    vk: VkSettings


def loadSettings() -> VkAdapterSettings:
    configValues = loadConfigValues()
    adapterRole = getSetting("VK_ADAPTER_ROLE", configValues, "USER").upper()
    defaultEndpoint = DEFAULT_ADMIN_ENDPOINT if adapterRole in {"ADMIN", "SUPER_ADMIN"} else "/api/v1/user"

    commonSettings = loadCommonSettings(default_admin_endpoint=defaultEndpoint, values=configValues)
    commonSettings = replace(commonSettings, api=replace(commonSettings.api, platform="VK"))

    return VkAdapterSettings(
        common=commonSettings,
        vk=VkSettings(
            token_file=Path(getSetting("VK_BOT_TOKEN_FILE", configValues, str(DEFAULT_TOKEN_FILE))),
            adapter_role=adapterRole,
        ),
    )


def getSetting(name: str, values: dict[str, str], default: str) -> str:
    return os.getenv(name) or values.get(name) or default
