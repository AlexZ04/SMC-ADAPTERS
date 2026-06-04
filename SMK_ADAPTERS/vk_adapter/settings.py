import os
from dataclasses import dataclass
from pathlib import Path

from SMK_ADAPTERS.common.config import CommonSettings, PROJECT_ROOT, loadCommonSettings
from SMK_ADAPTERS.common.constants import DEFAULT_ADMIN_ENDPOINT
from SMK_ADAPTERS.telegram_admin_adapter.settings import loadConfigValues


DEFAULT_TOKEN_FILE = PROJECT_ROOT / "SMK_ADAPTERS" / "vk_adapter" / "config" / "secrets" / "vk_bot_token.txt"
DEFAULT_ADMIN_TOKEN_FILE = (
    PROJECT_ROOT
    / "SMK_ADAPTERS"
    / "vk_admin_adapter"
    / "config"
    / "secrets"
    / "vk_admin_bot_token.txt"
)


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

    commonSettings = loadCommonSettings(default_admin_endpoint=defaultEndpoint, platform="VK", values=configValues)

    return VkAdapterSettings(
        common=commonSettings,
        vk=VkSettings(
            token_file=getTokenFile(adapterRole, configValues),
            adapter_role=adapterRole,
        ),
    )


def getSetting(name: str, values: dict[str, str], default: str) -> str:
    return os.getenv(name) or values.get(name) or default


def getTokenFile(adapterRole: str, values: dict[str, str]) -> Path:
    if adapterRole in {"ADMIN", "SUPER_ADMIN"}:
        return Path(getSetting("VK_ADMIN_BOT_TOKEN_FILE", values, str(DEFAULT_ADMIN_TOKEN_FILE)))

    return Path(getSetting("VK_BOT_TOKEN_FILE", values, str(DEFAULT_TOKEN_FILE)))
