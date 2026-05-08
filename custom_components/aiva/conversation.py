"""Conversation agent support for AIVA."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
import unicodedata
from typing import Any

from homeassistant.components import conversation
from homeassistant.components.conversation import ConversationEntity
from homeassistant.components.conversation.models import ConversationResult
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
import homeassistant.helpers.intent as intent

from .api import AivaApiError
from .const import (
    CONF_HOME_ID,
    CONF_PLAN,
    CONF_SECRET,
    DOMAIN,
    FIELD_CONVERSATION_ID,
    PLAN_PREMIUM,
    PLAN_SMART,
    STATE_ACTIVE,
    STATE_AWAITING_PAYMENT,
    STATE_SUSPENDED,
)

CONVERSATION_ENTITY_ID = "conversation.aiva"
SUPPORTED_PLANS = {PLAN_SMART, PLAN_PREMIUM}


async def async_setup_entry(
    hass,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the AIVA conversation agent."""
    runtime_data = hass.data[DOMAIN][entry.entry_id]
    runtime_data.conversation_entity_id = CONVERSATION_ENTITY_ID
    async_add_entities([AivaConversationEntity(runtime_data, entry)])


class AivaConversationEntity(ConversationEntity):
    """Expose AIVA as a Home Assistant conversation agent."""

    _attr_entity_id = CONVERSATION_ENTITY_ID
    _attr_name = "AIVA"
    _attr_supported_features = 0
    _attr_supported_languages = ["es", "es-AR", "en"]

    def __init__(self, runtime_data: Any, entry: ConfigEntry) -> None:
        """Initialize the AIVA conversation agent."""
        self.runtime_data = runtime_data
        self.entry = entry
        self.api = runtime_data.client
        self.coordinator = runtime_data.coordinator
        self._attr_unique_id = f"{entry.entry_id}_conversation"

    @property
    def supported_languages(self) -> list[str]:
        """Return supported conversation languages."""
        return self._attr_supported_languages

    async def async_process(self, user_input):
        """Process a conversation message for Home Assistant versions without ChatLog."""
        return await self._async_handle_message(user_input, _NullChatLog())

    async def _async_handle_message(self, user_input, chat_log: Any):
        """Handle an Assist message by forwarding safe text to AIVA."""
        language = user_input.language or self.hass.config.language or "es"
        text = (user_input.text or "").strip()
        conversation_id = user_input.conversation_id
        self._mark_request()

        validation_speech = await self._async_validation_error(language)
        if validation_speech is not None:
            self._mark_backend_status("blocked")
            return self._build_result(
                user_input=user_input,
                chat_log=chat_log,
                language=language,
                speech=validation_speech,
                conversation_id=conversation_id,
            )

        try:
            result = await self.api.process_conversation(
                text=text,
                language=language,
                conversation_id=conversation_id,
            )
        except AivaApiError as err:
            fallback = self._local_fallback(text, language)
            if fallback is None:
                fallback = self._speech(
                    language,
                    "No pude comunicarme con AIVA en este momento.",
                    "I could not reach AIVA right now.",
                )
            self._mark_error(err)
            return self._build_result(
                user_input=user_input,
                chat_log=chat_log,
                language=language,
                speech=fallback,
                conversation_id=conversation_id,
            )

        speech = str(result.get("speech") or result.get("text") or "").strip()
        if not speech:
            speech = self._speech(
                language,
                "AIVA no pudo preparar una respuesta en este momento.",
                "AIVA could not prepare a response right now.",
            )
        self._mark_backend_status("ok")

        return self._build_result(
            user_input=user_input,
            chat_log=chat_log,
            language=language,
            speech=speech,
            conversation_id=result.get(FIELD_CONVERSATION_ID) or conversation_id,
            continue_conversation=bool(result.get("continue_conversation", False)),
        )

    async def _async_validation_error(self, language: str) -> str | None:
        """Return a user-facing validation error, or None when allowed."""
        if not self.entry.data.get(CONF_HOME_ID) or not self.entry.data.get(CONF_SECRET):
            return self._speech(
                language,
                "AIVA todavía no está vinculada con esta casa.",
                "AIVA is not linked to this home yet.",
            )

        activation_state = self._current_activation_state()
        if activation_state == STATE_AWAITING_PAYMENT:
            return self._speech(
                language,
                "AIVA todavía está pendiente de activación.",
                "AIVA is still pending activation.",
            )
        if activation_state == STATE_SUSPENDED:
            return self._speech(
                language,
                "El servicio de AIVA está suspendido temporalmente.",
                "The AIVA service is temporarily suspended.",
            )

        plan = str(self.entry.data.get(CONF_PLAN) or "").strip().lower()
        if plan and plan not in SUPPORTED_PLANS:
            return self._speech(
                language,
                "La voz con AIVA no está incluida en tu plan actual.",
                "Voice with AIVA is not included in your current plan.",
            )

        if activation_state is None or not plan:
            try:
                activation = await self.api.get_activation_status()
            except AivaApiError:
                return self._speech(
                    language,
                    "No pude comunicarme con AIVA en este momento.",
                    "I could not reach AIVA right now.",
                )
            activation_state = activation.state
            if not plan:
                plan = str(activation.plan or "").strip().lower()
            if hasattr(self.coordinator, "activation_state"):
                self.coordinator.activation_state = activation_state

        if activation_state == STATE_AWAITING_PAYMENT:
            return self._speech(
                language,
                "AIVA todavía está pendiente de activación.",
                "AIVA is still pending activation.",
            )
        if activation_state == STATE_SUSPENDED:
            return self._speech(
                language,
                "El servicio de AIVA está suspendido temporalmente.",
                "The AIVA service is temporarily suspended.",
            )
        if activation_state != STATE_ACTIVE:
            return self._speech(
                language,
                "AIVA todavía está pendiente de activación.",
                "AIVA is still pending activation.",
            )
        if plan not in SUPPORTED_PLANS:
            return self._speech(
                language,
                "La voz con AIVA no está incluida en tu plan actual.",
                "Voice with AIVA is not included in your current plan.",
            )

        return None

    def _current_activation_state(self) -> str | None:
        """Return the latest known activation state."""
        state = getattr(self.coordinator, "activation_state", None)
        if isinstance(state, str) and state:
            return state
        data = getattr(self.coordinator, "data", None)
        state = getattr(data, "activation_state", None)
        if isinstance(state, str) and state:
            return state
        if getattr(data, "connected", False):
            return STATE_ACTIVE
        return None

    def _local_fallback(self, text: str, language: str) -> str | None:
        """Answer simple status questions locally when the backend is unavailable."""
        normalized = _normalize_text(text)
        if "verifica conexion" in normalized:
            return self._speech(
                language,
                "La conexión con AIVA está activa.",
                "The AIVA connection is active.",
            )
        if "conectad" in normalized:
            return self._speech(
                language,
                "Sí, AIVA está conectada con esta casa.",
                "Yes, AIVA is connected to this home.",
            )
        if "estado de la casa" in normalized or "home status" in normalized:
            count = self._effective_entities_count()
            return self._speech(
                language,
                f"AIVA está activa. Tengo {count} entidades sincronizadas.",
                f"AIVA is active. I have {count} synced entities.",
            )
        return None

    def _effective_entities_count(self) -> int:
        """Return the current synchronized entity count."""
        data = getattr(self.coordinator, "data", None)
        entity_sync = getattr(data, "entity_sync", None)
        return int(getattr(entity_sync, "effective_entities_count", 0) or 0)

    def _build_result(
        self,
        *,
        user_input,
        chat_log: Any,
        language: str,
        speech: str,
        conversation_id: str | None,
        continue_conversation: bool = False,
    ):
        """Build a Home Assistant conversation result."""
        add_content = getattr(chat_log, "async_add_assistant_content_without_tools", None)
        if callable(add_content):
            assistant_content = getattr(conversation, "AssistantContent", None)
            content = (
                assistant_content(agent_id=user_input.agent_id, content=speech)
                if assistant_content is not None
                else SimpleNamespace(agent_id=user_input.agent_id, content=speech)
            )
            add_content(content)

        response = intent.IntentResponse(language=language)
        response.async_set_speech(speech)

        try:
            return ConversationResult(
                conversation_id=conversation_id,
                response=response,
                continue_conversation=continue_conversation,
            )
        except TypeError:
            return ConversationResult(response=response, conversation_id=conversation_id)

    def _mark_request(self) -> None:
        """Store safe request diagnostics."""
        self.runtime_data.conversation_last_request_at = datetime.now(timezone.utc)
        self.runtime_data.conversation_last_error = None

    def _mark_error(self, err: Exception) -> None:
        """Store safe error diagnostics."""
        self.runtime_data.conversation_last_error = type(err).__name__
        self._mark_backend_status("error")

    def _mark_backend_status(self, status: str) -> None:
        """Store the last conversation backend status."""
        self.runtime_data.conversation_backend_status = status

    @staticmethod
    def _speech(language: str, spanish: str, english: str) -> str:
        """Return a localized response."""
        return spanish if language.startswith("es") else english


def _normalize_text(text: str) -> str:
    """Normalize user text for small local fallback matching."""
    normalized = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in normalized if not unicodedata.combining(char))


class _NullChatLog:
    """Chat log fallback for Home Assistant versions without ChatLog."""

    def async_add_assistant_content_without_tools(self, content) -> None:
        """Accept assistant content when no Home Assistant chat log exists."""
