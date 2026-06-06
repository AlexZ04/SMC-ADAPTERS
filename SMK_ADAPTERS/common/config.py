import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse, urlunparse


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True, slots=True)
class ApiConfig:
    base_url: str
    admin_endpoint: str
    user_endpoint: str
    platform: str
    api_key: str
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class RabbitConfig:
    url: str
    heartbeat: int
    blocked_connection_timeout: int
    prefetch_count: int


@dataclass(frozen=True, slots=True)
class DeploymentConfig:
    environment: str
    queue_prefix: str


@dataclass(frozen=True, slots=True)
class MonitoringConfig:
    enabled: bool
    base_url: str
    endpoint: str
    api_key: str
    timeout_seconds: float
    queue_size: int


@dataclass(frozen=True, slots=True)
class CommonSettings:
    api: ApiConfig
    rabbit: RabbitConfig
    deployment: DeploymentConfig
    monitoring: MonitoringConfig


def loadCommonSettings(
    default_admin_endpoint: str,
    platform: str,
    values: dict[str, str] | None = None,
) -> CommonSettings:
    config_values = values or {}
    base_url = requireServerUrl(getSetting("SMC_API_BASE_URL", config_values))

    return CommonSettings(
        api=ApiConfig(
            base_url=base_url.rstrip("/"),
            admin_endpoint=normalizeAdminEndpoint(
                getSetting("SMC_API_ADMIN_ENDPOINT", config_values, default_admin_endpoint)
            ),
            user_endpoint=getSetting("SMC_API_USER_ENDPOINT", config_values, "/api/v1/user"),
            platform=platform,
            api_key=getApiKey(config_values),
            timeout_seconds=float(getSetting("SMC_API_TIMEOUT_SECONDS", config_values, "10")),
        ),
        rabbit=RabbitConfig(
            url=normalizeRabbitmqUrl(getSetting("RABBITMQ_URL", config_values, "amqp://guest:guest@127.0.0.1:5672/")),
            heartbeat=int(getSetting("RABBITMQ_HEARTBEAT", config_values, "60")),
            blocked_connection_timeout=int(getSetting("RABBITMQ_BLOCKED_CONNECTION_TIMEOUT", config_values, "30")),
            prefetch_count=int(getSetting("RABBITMQ_PREFETCH_COUNT", config_values, "10")),
        ),
        deployment=loadDeploymentConfig(config_values),
        monitoring=loadMonitoringConfig(config_values, base_url),
    )


def loadDeploymentConfig(values: dict[str, str]) -> DeploymentConfig:
    environment = normalizeDeploymentEnvironment(getSetting("SMC_ADAPTER_ENVIRONMENT", values, "test"))
    return DeploymentConfig(environment=environment, queue_prefix=environment)


def loadMonitoringConfig(values: dict[str, str], smc_api_base_url: str) -> MonitoringConfig:
    enabled = getSetting("SMC_MONITORING_ENABLED", values, "true").strip().lower() not in {"0", "false", "no", "off"}
    base_url = getSetting("SMC_MONITORING_BASE_URL", values, deriveMonitoringBaseUrl(smc_api_base_url))
    endpoint = getSetting("SMC_MONITORING_ENDPOINT", values, "/api/v1/events")
    api_key = getMonitoringApiKey(values)

    return MonitoringConfig(
        enabled=enabled,
        base_url=requireServerUrl(base_url).rstrip("/"),
        endpoint=endpoint,
        api_key=api_key,
        timeout_seconds=float(getSetting("SMC_MONITORING_TIMEOUT_SECONDS", values, "3")),
        queue_size=int(getSetting("SMC_MONITORING_QUEUE_SIZE", values, "256")),
    )


def normalizeDeploymentEnvironment(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"prod", "production"}:
        return "prod"
    if normalized in {"test", "testing", "stage", "staging"}:
        return "test"

    raise RuntimeError("SMC_ADAPTER_ENVIRONMENT должен быть prod или test")


def loadSecretFile(path: Path) -> str:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError as exc:
        raise RuntimeError(f"Файл с секретом не найден: {path}") from exc

    if not value:
        raise RuntimeError(f"Файл с секретом пустой: {path}")

    return value


def getEnv(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Обязательная переменная окружения не задана: {name}")
    return value


def getSetting(name: str, values: dict[str, str], default: str | None = None) -> str:
    value = os.getenv(name) or values.get(name) or default
    if not value:
        raise RuntimeError(f"Обязательная настройка не задана: {name}")
    return value


def getApiKey(values: dict[str, str]) -> str:
    value = os.getenv("SMC_API_KEY") or values.get("SMC_API_KEY")
    if value:
        return value

    key_file = Path(
        os.getenv("SMC_API_KEY_FILE")
        or values.get("SMC_API_KEY_FILE")
        or PROJECT_ROOT / "SMK_ADAPTERS" / "config" / "secrets" / "smc_api_key.txt"
    )

    return loadSecretFile(key_file)


def getMonitoringApiKey(values: dict[str, str]) -> str:
    value = os.getenv("SMC_MONITORING_API_KEY") or values.get("SMC_MONITORING_API_KEY")
    if value:
        return value

    key_file_value = os.getenv("SMC_MONITORING_API_KEY_FILE") or values.get("SMC_MONITORING_API_KEY_FILE")
    if key_file_value:
        return loadSecretFile(Path(key_file_value))

    return getApiKey(values)


def deriveMonitoringBaseUrl(smc_api_base_url: str) -> str:
    parsed = urlparse(smc_api_base_url)
    path = parsed.path.rstrip("/")
    if path.endswith("/smc-api"):
        path = f"{path[: -len('/smc-api')]}/smc-monitoring"
    elif path == "/smc-api":
        path = "/smc-monitoring"
    else:
        path = "/smc-monitoring"

    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            path,
            "",
            "",
            "",
        )
    )


def requireServerUrl(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError("SMC_API_BASE_URL должен быть абсолютным http(s) URL")

    host = (parsed.hostname or "").lower()
    if host in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}:
        raise RuntimeError("SMC_API_BASE_URL должен указывать на сервер, а не на локальный адрес")

    return value


def normalizeRabbitmqUrl(value: str) -> str:
    parsed = urlparse(value)
    if (parsed.hostname or "").lower() != "localhost":
        return value

    user_info = ""
    if parsed.username:
        user_info = parsed.username
        if parsed.password:
            user_info += f":{parsed.password}"
        user_info += "@"

    port = f":{parsed.port}" if parsed.port else ""
    netloc = f"{user_info}127.0.0.1{port}"

    return urlunparse(
        (
            parsed.scheme,
            netloc,
            parsed.path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )


def normalizeAdminEndpoint(value: str) -> str:
    if value == "/api/admin/telegram/messages":
        return "/api/v1/admin"

    return value
