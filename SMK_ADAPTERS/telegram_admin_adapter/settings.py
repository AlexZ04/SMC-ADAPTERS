import os
from dataclasses import dataclass
from pathlib import Path

from SMK_ADAPTERS.common.config import CommonSettings, PROJECT_ROOT, loadCommonSettings
from SMK_ADAPTERS.common.constants import DEFAULT_ADMIN_ENDPOINT


DEFAULT_TOKEN_FILE = (
    PROJECT_ROOT
    / "SMK_ADAPTERS"
    / "telegram_admin_adapter"
    / "config"
    / "secrets"
    / "telegram_admin_bot_token.txt"
)
DEFAULT_SETTINGS_FILE = PROJECT_ROOT / "SMK_ADAPTERS" / "config" / "settings.env"


@dataclass(frozen=True, slots=True)
class TelegramSettings:
    token_file: Path
    poll_timeout_seconds: int
    retry_delay_seconds: float
    proxy_url: str | None = None


@dataclass(frozen=True, slots=True)
class TelegramAdminSettings:
    common: CommonSettings
    telegram: TelegramSettings


def loadSettings() -> TelegramAdminSettings:
    config_values = loadConfigValues()

    return TelegramAdminSettings(
        common=loadCommonSettings(default_admin_endpoint=DEFAULT_ADMIN_ENDPOINT, values=config_values),
        telegram=TelegramSettings(
            token_file=Path(getSetting("TELEGRAM_ADMIN_TOKEN_FILE", config_values, str(DEFAULT_TOKEN_FILE))),
            poll_timeout_seconds=int(getSetting("TELEGRAM_POLL_TIMEOUT_SECONDS", config_values, "30")),
            retry_delay_seconds=float(getSetting("TELEGRAM_RETRY_DELAY_SECONDS", config_values, "3")),
            proxy_url=getOptionalSetting("TELEGRAM_PROXY_URL", config_values),
        ),
    )


def loadConfigValues() -> dict[str, str]:
    return loadEnvFile(DEFAULT_SETTINGS_FILE)


def loadEnvFile(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue

        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")

    return values


def getSetting(name: str, values: dict[str, str], default: str) -> str:
    return os.getenv(name) or values.get(name) or default


def getOptionalSetting(name: str, values: dict[str, str]) -> str | None:
    value = os.getenv(name) or values.get(name)
    if value is None:
        return None

    stripped = value.strip()
    return stripped or None
