import json
import logging
import time
from collections.abc import Callable
from typing import Any

from SMK_ADAPTERS.common.config import RabbitConfig


LOGGER = logging.getLogger(__name__)


class MessageProvider:
    def __init__(self, config: RabbitConfig) -> None:
        self._config = config
        self._pika: Any | None = None
        self._connection: Any | None = None
        self._channel: Any | None = None

    def connect(self) -> None:
        pika = self.loadPika()
        parameters = pika.URLParameters(self._config.url)
        parameters.heartbeat = self._config.heartbeat
        parameters.blocked_connection_timeout = self._config.blocked_connection_timeout

        self.close()
        self._connection = pika.BlockingConnection(parameters)
        self._channel = self._connection.channel()
        self._channel.basic_qos(prefetch_count=self._config.prefetch_count)

    def close(self) -> None:
        try:
            if self._connection and self._connection.is_open:
                self._connection.close()
        except Exception:
            LOGGER.debug("Не удалось корректно закрыть соединение RabbitMQ", exc_info=True)
        finally:
            self._connection = None
            self._channel = None

    def publishJson(self, queue_name: str, payload: dict[str, Any]) -> None:
        pika = self.loadPika()

        for attempt in range(2):
            try:
                self.ensureConnected()
                self.publishJsonPrepared(queue_name, payload)
                return
            except pika.exceptions.AMQPError:
                self.close()
                if attempt == 1:
                    LOGGER.exception("Не удалось опубликовать сообщение в RabbitMQ")
                    raise

                LOGGER.warning("Соединение RabbitMQ было потеряно при публикации. Переподключаемся...")
                time.sleep(1)

    def consumeJson(self, queue_name: str, handler: Callable[[dict[str, Any]], None]) -> None:
        channel = self.requireChannel()
        channel.queue_declare(queue=queue_name, durable=True)

        def callback(channel: Any, method: Any, properties: Any, body: bytes) -> None:
            try:
                payload = json.loads(body.decode("utf-8"))
                handler(payload)
            except Exception:
                LOGGER.exception("Не удалось обработать сообщение RabbitMQ")
                channel.basic_nack(method.delivery_tag, requeue=True)
                return

            channel.basic_ack(method.delivery_tag)

        channel.basic_consume(queue=queue_name, on_message_callback=callback)
        channel.start_consuming()

    def sendToQueue(self, queue_name: str, payload: dict[str, Any]) -> None:
        self.publishJson(queue_name, payload)

    def reconnectForever(self) -> None:
        pika = self.loadPika()
        while True:
            try:
                self.connect()
                return
            except pika.exceptions.AMQPError:
                LOGGER.exception("Не удалось подключиться к RabbitMQ")
                time.sleep(5)

    def publishJsonPrepared(self, queue_name: str, payload: dict[str, Any]) -> None:
        pika = self.loadPika()
        channel = self.requireChannel()
        channel.queue_declare(queue=queue_name, durable=True)
        channel.basic_publish(
            exchange="",
            routing_key=queue_name,
            body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            properties=pika.BasicProperties(
                content_type="application/json",
                delivery_mode=pika.DeliveryMode.Persistent,
            ),
        )

    def ensureConnected(self) -> None:
        if self._connection is None or self._connection.is_closed:
            self.connect()
            return

        if self._channel is None or self._channel.is_closed:
            self._channel = self._connection.channel()
            self._channel.basic_qos(prefetch_count=self._config.prefetch_count)

    def requireChannel(self) -> Any:
        if self._channel is None or self._channel.is_closed:
            raise RuntimeError("Канал RabbitMQ не подключен")
        return self._channel

    def loadPika(self) -> Any:
        if self._pika is not None:
            return self._pika

        try:
            import pika
        except ImportError as exc:
            raise RuntimeError("Не найдена зависимость RabbitMQ. Сначала установите requirements.txt.") from exc

        self._pika = pika
        return pika


class RabbitMqBus(MessageProvider):
    pass
