# Деплой адаптеров

Workflow: `.github/workflows/deploy.yml`

Запускается при push в `master` и вручную через `workflow_dispatch`.

## GitHub Secrets

Обязательные секреты репозитория:

- `VPS_USER` - пользователь на сервере.
- `VPS_HOST` - хост или IP сервера.
- `VPS_SSH_KEY` - приватный SSH-ключ для доступа к серверу.

Необязательный секрет:

- `VPS_PORT` - SSH-порт. Если не задан, используется `22`.

## Что создается на сервере

Код разворачивается в:

```text
/home/${VPS_USER}/smc-adapters
```

Скрипт `deploy/install-systemd.sh` создает venv, ставит зависимости и регистрирует сервисы:

- `smc-telegram-admin-adapter.service`
- `smc-vk-user-adapter.service`
- `smc-vk-admin-adapter.service`

Оба сервиса запускаются через systemd с `Restart=always`.

RabbitMQ тоже поднимается этим же скриптом через `docker compose`:

- контейнер: `smc-rabbitmq`
- образ: `rabbitmq:3.13-management`
- restart policy: `unless-stopped`
- AMQP: `127.0.0.1:5672`
- management UI: `127.0.0.1:15672`

Порты RabbitMQ привязаны к `127.0.0.1`, чтобы брокер и management UI не были доступны из интернета.

## Файлы, которые нужно положить на сервер

Файл конфига:

```text
/home/${VPS_USER}/smc-adapters/SMK_ADAPTERS/config/settings.env
```

Минимальный пример для прода:

```env
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
```

Если с сервера нет прямого доступа к `api.telegram.org:443`, укажите прокси:

```env
TELEGRAM_PROXY_URL=socks5://user:password@host:port
```

Также поддерживается HTTP-прокси:

```env
TELEGRAM_PROXY_URL=http://user:password@host:port
```

Секреты на сервере:

```text
/home/${VPS_USER}/smc-adapters/SMK_ADAPTERS/config/secrets/smc_api_key.txt
/home/${VPS_USER}/smc-adapters/SMK_ADAPTERS/telegram_admin_adapter/config/secrets/telegram_admin_bot_token.txt
/home/${VPS_USER}/smc-adapters/SMK_ADAPTERS/vk_adapter/config/secrets/vk_bot_token.txt
/home/${VPS_USER}/smc-adapters/SMK_ADAPTERS/vk_admin_adapter/config/secrets/vk_admin_bot_token.txt
```

Workflow эти значения не получает и не хранит.

## Обновление конфига на сервере

Откройте общий конфиг:

```bash
nano ~/smc-adapters/SMK_ADAPTERS/config/settings.env
```

Текущий VK user adapter всегда работает как пользовательский. VK admin adapter запускается отдельным сервисом и принудительно использует роль `ADMIN`, поэтому `VK_ADAPTER_ROLE` в общем конфиге больше не нужен.

Если нужно явно переопределить пути к токенам:

```env
VK_BOT_TOKEN_FILE=/home/deploy/smc-adapters/SMK_ADAPTERS/vk_adapter/config/secrets/vk_bot_token.txt
VK_ADMIN_BOT_TOKEN_FILE=/home/deploy/smc-adapters/SMK_ADAPTERS/vk_admin_adapter/config/secrets/vk_admin_bot_token.txt
```

После изменения конфига перезапустите нужный сервис:

```bash
sudo systemctl restart smc-vk-user-adapter
sudo systemctl restart smc-vk-admin-adapter
```

Логи:

```bash
sudo journalctl -u smc-vk-user-adapter -f
sudo journalctl -u smc-vk-admin-adapter -f
```
