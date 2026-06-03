from SMK_ADAPTERS.common.macros import TriggerUser, replaceUserMacros
from SMK_ADAPTERS.common.models import BackendResponse, QueueMessage


class BackendResponseParser:
    def parseForAdminQueue(
        self,
        response: BackendResponse,
        adapter_name: str,
        trigger_user: TriggerUser | None = None,
    ) -> QueueMessage | None:
        if not response.recipient_id or not response.text:
            return None

        return QueueMessage.create(
            recipient_id=response.recipient_id,
            text=self.transformText(response.text, trigger_user),
            adapter=adapter_name,
            preview_messages=[self.transformText(message, trigger_user) for message in response.preview_messages],
            files_ids=response.files_ids,
            inline_elements=response.inline_elements,
            reply_elements=response.reply_elements,
            metadata={"source": "smc.api", "raw": response.raw_payload},
        )

    def transformText(self, text: str, trigger_user: TriggerUser | None = None) -> str:
        return replaceUserMacros(text, trigger_user)
