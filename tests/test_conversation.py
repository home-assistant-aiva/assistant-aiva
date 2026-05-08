"""Tests for the AIVA conversation agent."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.aiva import PLATFORMS
from custom_components.aiva.conversation import (
    AivaConversationEntity,
    CONVERSATION_ENTITY_ID,
    async_setup_entry,
)
from custom_components.aiva.api import AivaActivationStatus, AivaConnectionError
from custom_components.aiva.coordinator import AivaCoordinatorData, AivaEntitySyncStats
from custom_components.aiva.const import (
    CONF_HOME_ID,
    CONF_HOME_NAME,
    CONF_PLAN,
    CONF_SECRET,
    DOMAIN,
    PLAN_BASE,
    PLAN_SMART,
    STATE_ACTIVE,
    STATE_AWAITING_PAYMENT,
    STATE_SUSPENDED,
)


class FakeChatLog:
    """Small chat log double that records assistant content."""

    def __init__(self) -> None:
        """Initialize the fake chat log."""
        self.messages: list[str] = []

    def async_add_assistant_content_without_tools(self, content) -> None:
        """Record assistant content."""
        self.messages.append(content.content)


def _entry(plan: str = PLAN_SMART) -> MockConfigEntry:
    data = {
        CONF_HOME_ID: "home-1",
        CONF_HOME_NAME: "Casa Principal",
        CONF_SECRET: "<redacted-secret>",
    }
    if plan:
        data[CONF_PLAN] = plan
    return MockConfigEntry(
        domain=DOMAIN,
        title="Casa Principal",
        data=data,
        entry_id="test-entry",
        unique_id="home-1",
    )


def _runtime(
    *,
    plan: str = PLAN_SMART,
    activation_state: str = STATE_ACTIVE,
    backend_response: dict | None = None,
):
    api = AsyncMock()
    api.process_conversation.return_value = backend_response or {
        "speech": "Respuesta desde AIVA"
    }
    coordinator = SimpleNamespace(
        activation_state=activation_state,
        data=AivaCoordinatorData(
            state=activation_state,
            connected=activation_state == STATE_ACTIVE,
            home_name="Casa Principal",
            last_sync=None,
            activation_state=activation_state,
            entity_sync=AivaEntitySyncStats(effective_entities_count=3),
        ),
    )
    return SimpleNamespace(
        client=api,
        coordinator=coordinator,
        integration_version="0.2.17",
        conversation_entity_id=CONVERSATION_ENTITY_ID,
        conversation_last_request_at=None,
        conversation_last_error=None,
        conversation_backend_status=None,
    )


def _user_input(text: str):
    return SimpleNamespace(
        text=text,
        language="es",
        conversation_id="conv-1",
        agent_id=CONVERSATION_ENTITY_ID,
    )


async def test_conversation_platform_registers_entity(hass):
    """Register the AIVA conversation entity from the config entry."""
    entry = _entry()
    runtime = _runtime()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = runtime
    added = []

    await async_setup_entry(hass, entry, added.extend)

    assert any(platform.value == "conversation" for platform in PLATFORMS)
    assert len(added) == 1
    assert added[0].name == "AIVA"
    assert added[0].unique_id == "test-entry_conversation"
    assert runtime.conversation_entity_id == CONVERSATION_ENTITY_ID


async def test_plan_base_returns_voice_not_included():
    """Block voice use for the base plan before contacting the backend."""
    runtime = _runtime(plan=PLAN_BASE)
    entity = AivaConversationEntity(runtime, _entry(plan=PLAN_BASE))
    chat_log = FakeChatLog()

    await entity._async_handle_message(_user_input("Hola AIVA"), chat_log)

    assert chat_log.messages == [
        "La voz con AIVA no está incluida en tu plan actual."
    ]
    runtime.client.process_conversation.assert_not_awaited()


async def test_smart_active_sends_conversation_to_backend():
    """Forward Assist text to the AIVA backend for active Smart homes."""
    runtime = _runtime()
    entity = AivaConversationEntity(runtime, _entry())
    chat_log = FakeChatLog()

    await entity._async_handle_message(_user_input("Prendé la luz"), chat_log)

    runtime.client.process_conversation.assert_awaited_once_with(
        text="Prendé la luz",
        language="es",
        conversation_id="conv-1",
    )
    assert chat_log.messages == ["Respuesta desde AIVA"]
    assert runtime.conversation_backend_status == "ok"


async def test_missing_plan_uses_activation_status_for_existing_entries():
    """Keep older entries usable when activation status reports an allowed plan."""
    runtime = _runtime(activation_state="")
    runtime.client.get_activation_status.return_value = AivaActivationStatus(
        state=STATE_ACTIVE,
        home_id="home-1",
        secret="<redacted-secret>",
        home_name="Casa Principal",
        plan=PLAN_SMART,
    )
    entity = AivaConversationEntity(runtime, _entry(plan=""))
    chat_log = FakeChatLog()

    await entity._async_handle_message(_user_input("Hola"), chat_log)

    runtime.client.get_activation_status.assert_awaited_once()
    runtime.client.process_conversation.assert_awaited_once()
    assert chat_log.messages == ["Respuesta desde AIVA"]


@pytest.mark.parametrize(
    ("state", "speech"),
    [
        (STATE_AWAITING_PAYMENT, "AIVA todavía está pendiente de activación."),
        (STATE_SUSPENDED, "El servicio de AIVA está suspendido temporalmente."),
    ],
)
async def test_activation_states_block_conversation(state, speech):
    """Return clear messages for non-active commercial states."""
    runtime = _runtime(activation_state=state)
    entity = AivaConversationEntity(runtime, _entry())
    chat_log = FakeChatLog()

    await entity._async_handle_message(_user_input("Hola"), chat_log)

    assert chat_log.messages == [speech]
    runtime.client.process_conversation.assert_not_awaited()


async def test_backend_down_returns_clear_message():
    """Return a clear message when the conversation backend is unavailable."""
    runtime = _runtime()
    runtime.client.process_conversation.side_effect = AivaConnectionError("down")
    entity = AivaConversationEntity(runtime, _entry())
    chat_log = FakeChatLog()

    await entity._async_handle_message(_user_input("Abrí la puerta"), chat_log)

    assert chat_log.messages == ["No pude comunicarme con AIVA en este momento."]
    assert runtime.conversation_last_error == "AivaConnectionError"
    assert runtime.conversation_backend_status == "error"


async def test_connected_fallback_works_when_backend_is_down():
    """Answer simple connectivity questions locally as a fallback."""
    runtime = _runtime()
    runtime.client.process_conversation.side_effect = AivaConnectionError("down")
    entity = AivaConversationEntity(runtime, _entry())
    chat_log = FakeChatLog()

    await entity._async_handle_message(_user_input("AIVA, ¿estás conectada?"), chat_log)

    assert chat_log.messages == ["Sí, AIVA está conectada con esta casa."]
