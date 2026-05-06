"""Tests for the AIVA coordinator."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from custom_components.aiva.api import (
    AivaActivationStatus,
    AivaConnectionError,
    AivaEffectiveEntity,
    AivaHomeAutomation,
    AivaHomeSettings,
    AivaInvalidResponseError,
    AivaStatus,
)
from custom_components.aiva.coordinator import AivaDataUpdateCoordinator
from custom_components.aiva.const import STATE_ACTIVE, STATE_UNAVAILABLE


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
    client.get_activation_status.return_value = AivaActivationStatus(
        state=STATE_ACTIVE,
        home_name="Casa Principal",
        home_id="home-1",
        secret="<redacted-secret>",
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

    assert data.state == STATE_ACTIVE
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
    client.get_activation_status.return_value = AivaActivationStatus(
        state=STATE_ACTIVE,
        home_name="Casa Principal",
        home_id="home-1",
        secret="<redacted-secret>",
    )
    client.get_home_settings.side_effect = AivaInvalidResponseError("bad settings")
    client.get_effective_entities.side_effect = AivaInvalidResponseError("bad entities")
    client.get_home_automations.side_effect = AivaInvalidResponseError(
        "bad automations"
    )
    coordinator = AivaDataUpdateCoordinator(hass, client, 300)

    data = await coordinator._async_update_data()

    assert data.state == STATE_ACTIVE
    assert data.connected is True
    assert data.home_settings is None
    assert data.effective_entities == ()
    assert data.home_automations == ()


@pytest.mark.asyncio
async def test_coordinator_returns_unavailable_when_backend_fails_at_startup(hass):
    """Do not break setup/update when AIVA is temporarily unreachable."""
    client = AsyncMock()
    client.get_status.side_effect = AivaConnectionError("backend down")
    coordinator = AivaDataUpdateCoordinator(hass, client, 300)

    data = await coordinator._async_update_data()

    assert data.state == STATE_UNAVAILABLE
    assert data.connected is False
    assert coordinator.reconnect_state == STATE_UNAVAILABLE
    assert coordinator.last_heartbeat_error == "backend down"


@pytest.mark.asyncio
async def test_reconnect_success_marks_connected_and_syncs_entities(hass, monkeypatch):
    """A successful reconnect sends heartbeat, checks activation, then syncs."""
    client = AsyncMock()
    client.heartbeat.return_value = {"ok": True}
    client.get_activation_status.return_value = AivaActivationStatus(
        state=STATE_ACTIVE,
        home_name="Casa Principal",
        home_id="home-1",
        secret="<redacted-secret>",
    )
    client.get_status.return_value = AivaStatus(
        state="Activo",
        connected=True,
        home_name="Casa Principal",
        last_sync=None,
    )
    client.get_home_settings.return_value = AivaHomeSettings(language="es")
    client.get_effective_entities.return_value = ()
    client.get_home_automations.return_value = ()
    coordinator = AivaDataUpdateCoordinator(hass, client, 300)
    refresh = AsyncMock()
    monkeypatch.setattr(coordinator, "async_request_refresh", refresh)
    hass.states.async_set("input_boolean.luz_living_prueba", "on")

    await coordinator.async_reconnect(reason="test")

    client.heartbeat.assert_awaited_once()
    client.get_activation_status.assert_awaited_once()
    client.sync_entities.assert_awaited_once()
    assert coordinator.data.connected is True
    assert coordinator.reconnect_state == STATE_ACTIVE
    assert coordinator.last_reconnect_success_at is not None
    assert coordinator.last_heartbeat_success_at is not None
    assert coordinator.last_sync_success_at is not None


@pytest.mark.asyncio
async def test_reconnect_keeps_connected_when_entity_sync_fails(hass, monkeypatch):
    """Entity sync failures are recorded without losing a working connection."""
    client = AsyncMock()
    client.heartbeat.return_value = {"ok": True}
    client.get_activation_status.return_value = AivaActivationStatus(
        state=STATE_ACTIVE,
        home_name="Casa Principal",
        home_id="home-1",
        secret="<redacted-secret>",
    )
    client.get_status.return_value = AivaStatus(
        state="Activo",
        connected=True,
        home_name="Casa Principal",
        last_sync=None,
    )
    client.get_home_settings.return_value = AivaHomeSettings(language="es")
    client.get_effective_entities.return_value = ()
    client.get_home_automations.return_value = ()
    client.sync_entities.side_effect = AivaInvalidResponseError("sync failed")
    coordinator = AivaDataUpdateCoordinator(hass, client, 300)
    refresh = AsyncMock()
    monkeypatch.setattr(coordinator, "async_request_refresh", refresh)

    await coordinator.async_reconnect(reason="test")

    assert coordinator.data.connected is True
    assert coordinator.reconnect_state == STATE_ACTIVE
    assert coordinator.last_sync_error == "sync failed"
    refresh.assert_awaited_once()


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


def test_collect_entities_includes_useful_helpers_without_device_id(hass):
    """Helpers are useful entities even when they do not have a device entry."""
    client = AsyncMock()
    coordinator = AivaDataUpdateCoordinator(hass, client, 300)
    hass.states.async_set(
        "input_boolean.luz_living_prueba",
        "on",
        {"friendly_name": "Luz living prueba"},
    )
    hass.states.async_set(
        "input_boolean.alarma_de_prueba",
        "off",
        {"friendly_name": "Alarma de prueba"},
    )
    hass.states.async_set(
        "input_select.modo_casa_prueba",
        "Dia",
        {
            "friendly_name": "Modo casa prueba",
            "options": ["Dia", "Noche"],
            "icon": "mdi:home",
        },
    )

    entities = coordinator._collect_entities()
    entity_ids = {entity["entity_id"] for entity in entities}

    assert "input_boolean.luz_living_prueba" in entity_ids
    assert "input_boolean.alarma_de_prueba" in entity_ids
    assert "input_select.modo_casa_prueba" in entity_ids
    assert coordinator._last_entity_sync_stats.effective_entities_count == 3
    assert coordinator._last_entity_sync_stats.has_input_boolean is True
    assert coordinator._last_entity_sync_stats.has_input_select is True

    input_select_payload = next(
        entity
        for entity in entities
        if entity["entity_id"] == "input_select.modo_casa_prueba"
    )
    assert input_select_payload["options"] == ["Dia", "Noche"]
    assert input_select_payload["area"] is None


def test_collect_entities_excludes_aiva_internal_entities(hass):
    """AIVA must not count its own sensors or buttons as useful entities."""
    client = AsyncMock()
    coordinator = AivaDataUpdateCoordinator(hass, client, 300)
    hass.states.async_set("sensor.aiva_estado", "Activo")
    hass.states.async_set("button.aiva_actualizar_dispositivos", "unknown")
    hass.states.async_set("light.living", "on")

    entities = coordinator._collect_entities()
    entity_ids = {entity["entity_id"] for entity in entities}

    assert "light.living" in entity_ids
    assert "sensor.aiva_estado" not in entity_ids
    assert "button.aiva_actualizar_dispositivos" not in entity_ids
    assert coordinator._last_entity_sync_stats.effective_entities_count == 1


def test_collect_entities_sends_unavailable_but_does_not_count_effective(hass):
    """Unavailable useful entities stay diagnostic-only in the payload."""
    client = AsyncMock()
    coordinator = AivaDataUpdateCoordinator(hass, client, 300)
    hass.states.async_set("switch.bomba", "unavailable")

    entities = coordinator._collect_entities()

    assert entities[0]["entity_id"] == "switch.bomba"
    assert entities[0]["available"] is False
    assert entities[0]["effective"] is False
    assert coordinator._last_entity_sync_stats.effective_entities_count == 0


@pytest.mark.asyncio
async def test_sync_entities_recalculates_current_entities(hass, monkeypatch):
    """The sync button path sends the current local snapshot."""
    client = AsyncMock()
    coordinator = AivaDataUpdateCoordinator(hass, client, 300)
    refresh = AsyncMock()
    monkeypatch.setattr(coordinator, "async_request_refresh", refresh)
    hass.states.async_set("input_boolean.luz_living_prueba", "on")

    await coordinator.async_sync_entities()

    payload = client.sync_entities.await_args.args[0]
    assert payload[0]["entity_id"] == "input_boolean.luz_living_prueba"
    assert coordinator._last_entity_sync_stats.effective_entities_count == 1
    refresh.assert_awaited_once()
