"""Tests for the AIVA coordinator."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from custom_components.aiva.api import (
    AivaEffectiveEntity,
    AivaHomeAutomation,
    AivaHomeSettings,
    AivaInvalidResponseError,
    AivaStatus,
)
from custom_components.aiva.coordinator import AivaDataUpdateCoordinator


@pytest.mark.asyncio
async def test_coordinator_loads_enriched_data(hass):
    """Load base status plus optional backend data."""
    client = AsyncMock()
    client.get_status.return_value = AivaStatus(
        state="Activo",
        connected=True,
        home_name="Casa Principal",
        last_sync=None,
    )
    client.get_home_settings.return_value = AivaHomeSettings(
        language="es",
        assistant_name="AIVA",
    )
    client.get_effective_entities.return_value = (
        AivaEffectiveEntity(
            entity_id="light.living",
            display_name="Luz living",
            is_allowed=True,
            is_visible=True,
        ),
    )
    client.get_home_automations.return_value = (
        AivaHomeAutomation(
            automation_id="auto-1",
            name="Apagar luces",
            enabled=True,
        ),
    )
    coordinator = AivaDataUpdateCoordinator(hass, client, 300)

    data = await coordinator._async_update_data()

    assert data.state == "Activo"
    assert data.connected is True
    assert data.home_settings.assistant_name == "AIVA"
    assert data.effective_entities[0].entity_id == "light.living"
    assert data.home_automations[0].automation_id == "auto-1"


@pytest.mark.asyncio
async def test_coordinator_keeps_base_data_when_optional_endpoint_fails(hass):
    """Do not fail the integration when optional enriched data fails."""
    client = AsyncMock()
    client.get_status.return_value = AivaStatus(
        state="Activo",
        connected=True,
        home_name="Casa Principal",
        last_sync=None,
    )
    client.get_home_settings.side_effect = AivaInvalidResponseError("bad settings")
    client.get_effective_entities.side_effect = AivaInvalidResponseError("bad entities")
    client.get_home_automations.side_effect = AivaInvalidResponseError(
        "bad automations"
    )
    coordinator = AivaDataUpdateCoordinator(hass, client, 300)

    data = await coordinator._async_update_data()

    assert data.state == "Activo"
    assert data.connected is True
    assert data.home_settings is None
    assert data.effective_entities == ()
    assert data.home_automations == ()


@pytest.mark.asyncio
async def test_sync_entities_keeps_existing_refresh_path(hass, monkeypatch):
    """Sync entities with AIVA and request a coordinator refresh."""
    client = AsyncMock()
    coordinator = AivaDataUpdateCoordinator(hass, client, 300)
    refresh = AsyncMock()
    monkeypatch.setattr(coordinator, "async_request_refresh", refresh)

    await coordinator.async_sync_entities()

    client.sync_entities.assert_awaited_once()
    refresh.assert_awaited_once()
