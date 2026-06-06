#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_USER="${SMC_ADAPTERS_USER:-$(id -un)}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="$APP_DIR/.venv"
CONFIG_FILE="$APP_DIR/SMK_ADAPTERS/config/settings.env"
COMMON_SECRET_DIR="$APP_DIR/SMK_ADAPTERS/config/secrets"
TG_SECRET_DIR="$APP_DIR/SMK_ADAPTERS/telegram_admin_adapter/config/secrets"
VK_SECRET_DIR="$APP_DIR/SMK_ADAPTERS/vk_adapter/config/secrets"
VK_ADMIN_SECRET_DIR="$APP_DIR/SMK_ADAPTERS/vk_admin_adapter/config/secrets"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Не найдена команда: $1" >&2
    exit 1
  fi
}

install_os_packages() {
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update
    sudo apt-get install -y python3 python3-venv python3-pip docker.io
    sudo apt-get install -y docker-compose-plugin || sudo apt-get install -y docker-compose
  fi
}

docker_compose() {
  if sudo docker compose version >/dev/null 2>&1; then
    sudo docker compose "$@"
    return
  fi

  if command -v docker-compose >/dev/null 2>&1; then
    sudo docker-compose "$@"
    return
  fi

  echo "Не найден docker compose" >&2
  exit 1
}

start_rabbitmq() {
  require_command docker

  if command -v systemctl >/dev/null 2>&1; then
    sudo systemctl enable --now docker
  fi

  docker_compose -f "$APP_DIR/docker-compose.yml" up -d rabbitmq
  wait_rabbitmq
}

wait_rabbitmq() {
  local container_name="smc-rabbitmq"
  local attempts=30

  for _ in $(seq 1 "$attempts"); do
    if sudo docker inspect --format='{{.State.Health.Status}}' "$container_name" 2>/dev/null | grep -q "healthy"; then
      echo "RabbitMQ запущен"
      return
    fi

    sleep 2
  done

  echo "RabbitMQ не стал healthy за отведенное время" >&2
  sudo docker logs "$container_name" || true
  exit 1
}

write_service() {
  local service_name="$1"
  local module_name="$2"
  local service_file="/etc/systemd/system/${service_name}.service"

  sudo tee "$service_file" >/dev/null <<SERVICE
[Unit]
Description=SMC adapters: ${service_name}
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${APP_USER}
WorkingDirectory=${APP_DIR}
Environment=PYTHONUNBUFFERED=1
ExecStart=${VENV_DIR}/bin/python -m ${module_name}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICE
}

create_config_template() {
  if [ -f "$CONFIG_FILE" ]; then
    return
  fi

  mkdir -p "$(dirname "$CONFIG_FILE")"
  cat > "$CONFIG_FILE" <<'CONFIG'
SMC_API_BASE_URL=http://91.227.18.176/smc-api
SMC_API_ADMIN_ENDPOINT=/api/v1/admin
SMC_API_USER_ENDPOINT=/api/v1/user
SMC_MONITORING_ENABLED=true
SMC_MONITORING_BASE_URL=http://91.227.18.176/smc-monitoring
SMC_MONITORING_ENDPOINT=/api/v1/events
SMC_ADAPTER_ENVIRONMENT=prod
RABBITMQ_URL=amqp://guest:guest@127.0.0.1:5672/
# TELEGRAM_PROXY_URL=socks5://user:password@host:port
LOG_LEVEL=INFO
CONFIG
  echo "Создан шаблон конфига: $CONFIG_FILE"
  echo "Проверьте значения перед запуском сервисов."
}

print_secret_hints() {
  echo "Проверьте, что на сервере существуют файлы секретов:"
  echo "  $COMMON_SECRET_DIR/smc_api_key.txt"
  echo "  $TG_SECRET_DIR/telegram_admin_bot_token.txt"
  echo "  $VK_SECRET_DIR/vk_bot_token.txt"
  echo "  $VK_ADMIN_SECRET_DIR/vk_admin_bot_token.txt"
}

validate_required_files() {
  local missing_files=0
  local required_files=(
    "$CONFIG_FILE"
    "$COMMON_SECRET_DIR/smc_api_key.txt"
    "$TG_SECRET_DIR/telegram_admin_bot_token.txt"
    "$VK_SECRET_DIR/vk_bot_token.txt"
    "$VK_ADMIN_SECRET_DIR/vk_admin_bot_token.txt"
  )

  for file_path in "${required_files[@]}"; do
    if [ ! -s "$file_path" ]; then
      echo "Не найден или пустой обязательный файл: $file_path" >&2
      missing_files=1
    fi
  done

  if [ "$missing_files" -ne 0 ]; then
    print_secret_hints
    exit 1
  fi
}

main() {
  require_command sudo
  install_os_packages
  require_command "$PYTHON_BIN"

  mkdir -p "$COMMON_SECRET_DIR" "$TG_SECRET_DIR" "$VK_SECRET_DIR" "$VK_ADMIN_SECRET_DIR"
  create_config_template
  validate_required_files
  start_rabbitmq

  "$PYTHON_BIN" -m venv "$VENV_DIR"
  "$VENV_DIR/bin/python" -m pip install --upgrade pip
  "$VENV_DIR/bin/python" -m pip install -r "$APP_DIR/requirements.txt"

  "$VENV_DIR/bin/python" -m compileall "$APP_DIR/SMK_ADAPTERS"

  write_service "smc-telegram-admin-adapter" "SMK_ADAPTERS.telegram_admin_adapter"
  write_service "smc-vk-user-adapter" "SMK_ADAPTERS.vk_adapter"
  write_service "smc-vk-admin-adapter" "SMK_ADAPTERS.vk_admin_adapter"

  sudo systemctl daemon-reload
  sudo systemctl disable --now smc-vk-adapter.service >/dev/null 2>&1 || true
  sudo systemctl enable smc-telegram-admin-adapter.service smc-vk-user-adapter.service smc-vk-admin-adapter.service
  sudo systemctl restart smc-telegram-admin-adapter.service smc-vk-user-adapter.service smc-vk-admin-adapter.service
  sudo systemctl --no-pager --full status smc-telegram-admin-adapter.service smc-vk-user-adapter.service smc-vk-admin-adapter.service || true

  print_secret_hints
}

main "$@"
