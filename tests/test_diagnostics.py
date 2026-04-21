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
from custom_components.aiva.coordinator import AivaCoordinatorData
from custom_components.aiva.const import (
    CONF_HOME_ID,
    CONF_HOME_NAME,
    CONF_PAIRING_CODE,
    CONF_SECRET,
    DOMAIN,
)
from custom_components.aiva.diagnostics import async_get_config_entry_diagnostics


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
        home_automations=(
            AivaHomeAutomation(
                automation_id="auto-1",
                name="Apagar luces",
                enabled=True,
            ),
        ),
    )
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = SimpleNamespace(
        coordinator=SimpleNamespace(
            data=coordinator_data,
            last_update_success=True,
            update_interval=None,
        )
    )

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["entry"]["data"][CONF_SECRET] == "**REDACTED**"
    assert diagnostics["entry"]["data"][CONF_PAIRING_CODE] == "1234...**REDACTED**"
    assert diagnostics["home_settings"]["custom_prompt_configured"] is True
    assert "custom_prompt" not in diagnostics["home_settings"]
    assert diagnostics["effective_entities"]["total_count"] == 1
    assert diagnostics["home_automations"]["enabled_count"] == 1
