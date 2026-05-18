"""Tests for AIVA diagnostics."""

from __future__ import annotations

from types import SimpleNamespace

from homeassistant import config_entries
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.aiva.api import (
    AivaEffectiveEntity,
    AivaHomeAutomation,
    AivaHomeSettings,
)
from custom_components.aiva.coordinator import AivaCoordinatorData, AivaEntitySyncStats
from custom_components.aiva.const import (
    CONF_HOME_ID,
    CONF_HOME_NAME,
    CONF_PAIRING_CODE,
    CONF_SECRET,
    DOMAIN,
)
from custom_components.aiva.diagnostics import async_get_config_entry_diagnostics
from custom_components.aiva.version import get_integration_version


async def test_diagnostics_redacts_sensitive_enriched_data(hass):
    """Diagnostics include useful summaries without sensitive content."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Casa Principal",
        data={
            CONF_HOME_ID: "home-1",
            CONF_HOME_NAME: "Casa Principal",
            CONF_SECRET: "<redacted-secret>",
            CONF_PAIRING_CODE: "1234567890",
        },
        source=config_entries.SOURCE_USER,
        entry_id="test-entry",
        unique_id="home-1",
    )
    entry.add_to_hass(hass)

    coordinator_data = AivaCoordinatorData(
        state="Activo",
        connected=True,
        home_name="Casa Principal",
        last_sync=None,
        home_settings=AivaHomeSettings(
            language="es",
            assistant_name="AIVA",
            custom_prompt="private prompt",
            country_code="AR",
        ),
        effective_entities=(
            AivaEffectiveEntity(
                entity_id="light.living",
                display_name="Luz living",
                is_allowed=True,
                is_visible=True,
                requires_confirmation=False,
            ),
        ),
        entity_sync=AivaEntitySyncStats(
            total_entities_seen=4,
            effective_entities_count=3,
            included_domains=("input_boolean", "input_select", "light"),
            excluded_domains_count={"sensor": 1},
            sample_effective_entities=(
                {
                    "entity_id": "input_boolean.luz_living_prueba",
                    "domain": "input_boolean",
                    "friendly_name": "Luz living prueba",
                    "area": None,
                    "state": "on",
                },
            ),
            has_input_boolean=True,
            has_input_select=True,
        ),
        home_automations=(
            AivaHomeAutomation(
                automation_id="auto-1",
                name="Apagar luces",
                enabled=True,
            ),
        ),
    )
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = SimpleNamespace(
        client=SimpleNamespace(
            base_url="https://user:pass@api.example.com/aiva?secret=bad"
        ),
        coordinator=SimpleNamespace(
            data=coordinator_data,
            last_update_success=True,
            update_interval=None,
            reconnect_state="active",
            activation_state="active",
            last_reconnect_attempt_at=None,
            last_reconnect_success_at=None,
            last_heartbeat_success_at=None,
            last_heartbeat_error=None,
            last_sync_success_at=None,
            last_sync_error=None,
        ),
        conversation_entity_id="conversation.aiva",
        conversation_last_request_at=None,
        conversation_last_error="AivaConnectionError",
        conversation_backend_status="error",
        security_manager=SimpleNamespace(
            security_enabled=True,
            security_sensor_entity_ids=("input_boolean.puerta_negocio_prueba",),
            last_security_config_update=None,
        ),
    )

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["integration"]["domain"] == DOMAIN
    assert diagnostics["integration"]["version"] == get_integration_version()
    assert diagnostics["entry"]["data"][CONF_SECRET] == "**REDACTED**"
    assert diagnostics["entry"]["data"][CONF_PAIRING_CODE] == "1234...**REDACTED**"
    assert diagnostics["home_settings"]["custom_prompt_configured"] is True
    assert "custom_prompt" not in diagnostics["home_settings"]
    assert diagnostics["effective_entities"]["total_count"] == 1
    assert diagnostics["entity_sync"]["effective_entities_count"] == 3
    assert diagnostics["entity_sync"]["has_input_boolean"] is True
    assert diagnostics["entity_sync"]["has_input_select"] is True
    assert diagnostics["home_automations"]["enabled_count"] == 1
    assert diagnostics["coordinator"]["reconnect_state"] == "active"
    assert diagnostics["coordinator"]["activation_state"] == "active"
    assert diagnostics["coordinator"]["effective_entities_count"] == 3
    assert diagnostics["coordinator"]["backend_base_url"] == "https://api.example.com/aiva"
    assert diagnostics["conversation"]["conversation_agent_enabled"] is True
    assert diagnostics["conversation"]["conversation_entity_id"] == "conversation.aiva"
    assert (
        diagnostics["conversation"]["conversation_last_error"]
        == "AivaConnectionError"
    )
    assert diagnostics["security"]["security_enabled"] is True
    assert diagnostics["security"]["security_sensor_count"] == 1
    assert diagnostics["security"]["security_sensor_entity_ids"] == [
        "input_boolean.puerta_negocio_prueba"
    ]
    assert "pass" not in str(diagnostics)
    assert "secret=bad" not in str(diagnostics)
