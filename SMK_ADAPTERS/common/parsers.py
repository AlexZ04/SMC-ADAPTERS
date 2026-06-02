from SMK_ADAPTERS.common.models import BackendResponse, QueueMessage


class BackendResponseParser:
    def parseForAdminQueue(self, response: BackendResponse, adapter_name: str) -> QueueMessage | None:
        if not response.recipient_id or not response.text:
            return None

        return QueueMessage.create(
            recipient_id=response.recipient_id,
            text=self.transformText(response.text),
            adapter=adapter_name,
            inline_elements=response.inline_elements,
            reply_elements=response.reply_elements,
            metadata={"source": "smc.api", "raw": response.raw_payload},
        )

    def transformText(self, text: str) -> str:
        return text
