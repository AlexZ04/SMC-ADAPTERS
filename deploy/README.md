# Деплой адаптеров

Workflow: `.github/workflows/deploy.yml`

Запускается при push в `main` и вручную через `workflow_dispatch`.

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
- `smc-vk-adapter.service`

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
SMC_API_PLATFORM=TG
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
```

Workflow эти значения не получает и не хранит.
