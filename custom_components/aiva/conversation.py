from __future__ import annotations

from typing import Any

from homeassistant.components import conversation
from homeassistant.components.conversation import (
    ChatLog,
    ConversationEntity,
    ConversationEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
import homeassistant.helpers.intent as intent

from .api import AivaError
from .const import DOMAIN, RUNTIME_API


async def async_setup_entry(
    hass,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    api = hass.data[DOMAIN][entry.entry_id][RUNTIME_API]
    async_add_entities([AivaConversationEntity(api, entry)])


class AivaConversationEntity(ConversationEntity):
    """Expose AIVA as a Home Assistant conversation agent."""

    _attr_name = "AIVA"
    _attr_supported_features = ConversationEntityFeature.CONTROL
    _attr_supported_languages = ["es", "es-AR", "en"]

    def __init__(self, api: Any, entry: ConfigEntry) -> None:
        self.api = api
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_conversation"

    async def _async_handle_message(self, user_input, chat_log: ChatLog):
        language = user_input.language or self.hass.config.language or "en"

        try:
            result = await self.api.process_conversation(
                text=user_input.text,
                language=language,
                conversation_id=user_input.conversation_id,
            )
        except AivaError:
            speech = (
                "AIVA no está disponible en este momento. "
                "Intentá nuevamente en unos minutos."
                if language.startswith("es")
                else "AIVA is not available right now. Try again in a few minutes."
            )
            continue_conversation = False
            new_conversation_id = user_input.conversation_id
        else:
            speech = str(result.get("speech") or result.get("text") or "").strip()
            if not speech:
                speech = (
                    "AIVA no pudo preparar una respuesta en este momento."
                    if language.startswith("es")
                    else "AIVA could not prepare a response right now."
                )

            continue_conversation = bool(result.get("continue_conversation", False))
            new_conversation_id = result.get("conversation_id") or user_input.conversation_id

        chat_log.async_add_assistant_content_without_tools(
            conversation.AssistantContent(
                agent_id=user_input.agent_id,
                content=speech,
            )
        )

        response = intent.IntentResponse(language=language)
        response.async_set_speech(speech)

        return conversation.ConversationResult(
            conversation_id=new_conversation_id,
            response=response,
            continue_conversation=continue_conversation,
        )
