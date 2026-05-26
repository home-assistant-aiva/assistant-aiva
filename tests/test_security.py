"""Tests for AIVA Seguridad Negocios."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.aiva.api import (
    AivaActivationStatus,
    AivaInvalidResponseError,
    AivaSecurityConfig,
    AivaSecuritySensor,
)
from custom_components.aiva.const import STATE_ACTIVE, STATE_AWAITING_PAYMENT
from custom_components.aiva.security import AivaSecurityManager


def _event(entity_id: str, old_state: str | None, new_state: str | None):
    return SimpleNamespace(
        data={
            "old_state": SimpleNamespace(entity_id=entity_id, state=old_state),
            "new_state": SimpleNamespace(entity_id=entity_id, state=new_state),
        }
    )


@pytest.mark.asyncio
async def test_security_does_not_register_listeners_when_disabled(hass, monkeypatch):
    """Disabled security config clears listeners and does not listen."""
    client = AsyncMock()
    client.home_id = "home-1"
    client.secret = "<redacted-home-secret>"
    client.get_activation_status.return_value = AivaActivationStatus(
        state=STATE_ACTIVE,
        active=True,
    )
    client.async_get_security_config.return_value = AivaSecurityConfig(
        security_enabled=False,
    )
    track = AsyncMock()
    monkeypatch.setattr(
        "custom_components.aiva.security.async_track_state_change_event",
        track,
    )
    manager = AivaSecurityManager(hass, client)

    await manager.async_refresh_config()

    assert manager.security_enabled is False
    assert manager.security_sensor_entity_ids == ()
    client.async_get_security_config.assert_awaited_once()
    track.assert_not_called()


@pytest.mark.asyncio
async def test_security_registers_only_active_sensors(hass, monkeypatch):
    """Only active backend sensors are listened to."""
    unsub = Mock()
    calls = []

    def _track(hass_arg, entity_ids, callback):
        calls.append((hass_arg, entity_ids, callback))
        return unsub

    client = AsyncMock()
    client.home_id = "home-1"
    client.secret = "<redacted-home-secret>"
    client.get_activation_status.return_value = AivaActivationStatus(
        state=STATE_ACTIVE,
        active=True,
    )
    client.async_get_security_config.return_value = AivaSecurityConfig(
        security_enabled=True,
        sensors=(
            AivaSecuritySensor(
                entity_id="input_boolean.puerta_negocio_prueba",
                is_active=True,
            ),
            AivaSecuritySensor(
                entity_id="input_boolean.sensor_inactivo",
                is_active=False,
            ),
        ),
    )
    monkeypatch.setattr(
        "custom_components.aiva.security.async_track_state_change_event",
        _track,
    )
    manager = AivaSecurityManager(hass, client)

    await manager.async_refresh_config()

    assert manager.security_enabled is True
    assert manager.security_sensor_entity_ids == (
        "input_boolean.puerta_negocio_prueba",
    )
    client.async_get_security_config.assert_awaited_once_with(
        "home-1",
        "<redacted-home-secret>",
    )
    assert calls[0][1] == ("input_boolean.puerta_negocio_prueba",)


@pytest.mark.asyncio
async def test_security_ignores_duplicate_and_unavailable_states(hass):
    """Do not send duplicate, unknown, or unavailable transitions."""
    client = AsyncMock()
    client.home_id = "home-1"
    client.secret = "<redacted-home-secret>"
    manager = AivaSecurityManager(hass, client)
    manager.security_enabled = True
    manager.security_sensor_entity_ids = ("input_boolean.puerta_negocio_prueba",)

    manager._handle_state_change(
        _event("input_boolean.puerta_negocio_prueba", "off", "off")
    )
    manager._handle_state_change(
        _event("input_boolean.puerta_negocio_prueba", "off", "unknown")
    )
    manager._handle_state_change(
        _event("input_boolean.puerta_negocio_prueba", "off", "unavailable")
    )
    await hass.async_block_till_done()

    client.async_send_security_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_security_sends_event_for_off_to_on_and_on_to_off(hass):
    """Send events for useful state changes."""
    client = AsyncMock()
    client.home_id = "home-1"
    client.secret = "<redacted-home-secret>"
    client.get_activation_status.return_value = AivaActivationStatus(
        state=STATE_ACTIVE,
        active=True,
    )
    client.async_send_security_event.return_value = {"ok": True}
    manager = AivaSecurityManager(hass, client)
    manager.security_enabled = True
    manager.security_sensor_entity_ids = ("input_boolean.puerta_negocio_prueba",)

    manager._handle_state_change(
        _event("input_boolean.puerta_negocio_prueba", "off", "on")
    )
    manager._handle_state_change(
        _event("input_boolean.puerta_negocio_prueba", "on", "off")
    )
    await hass.async_block_till_done()

    assert client.async_send_security_event.await_count == 2
    first_call = client.async_send_security_event.await_args_list[0].args
    second_call = client.async_send_security_event.await_args_list[1].args
    assert first_call[:4] == (
        "home-1",
        "<redacted-home-secret>",
        "input_boolean.puerta_negocio_prueba",
        "on",
    )
    assert second_call[:4] == (
        "home-1",
        "<redacted-home-secret>",
        "input_boolean.puerta_negocio_prueba",
        "off",
    )


@pytest.mark.asyncio
async def test_security_backend_failure_does_not_raise(hass):
    """Backend failures are logged by the manager and do not break HA."""
    client = AsyncMock()
    client.home_id = "home-1"
    client.secret = "<redacted-home-secret>"
    client.get_activation_status.return_value = AivaActivationStatus(
        state=STATE_ACTIVE,
        active=True,
    )
    client.async_send_security_event.side_effect = AivaInvalidResponseError("boom")
    manager = AivaSecurityManager(hass, client)
    manager.security_enabled = True
    manager.security_sensor_entity_ids = ("input_boolean.puerta_negocio_prueba",)

    manager._handle_state_change(
        _event("input_boolean.puerta_negocio_prueba", "off", "on")
    )
    await hass.async_block_till_done()

    client.async_send_security_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_security_awaiting_payment_does_not_load_config_or_send_events(hass):
    """Do not operate Seguridad Negocios until the single home activation is active."""
    client = AsyncMock()
    client.home_id = "home-1"
    client.secret = "<redacted-home-secret>"
    client.get_activation_status.return_value = AivaActivationStatus(
        state=STATE_AWAITING_PAYMENT,
        active=False,
    )
    manager = AivaSecurityManager(hass, client)
    manager.security_enabled = True
    manager.security_sensor_entity_ids = ("input_boolean.puerta_negocio_prueba",)

    await manager.async_refresh_config()
    manager.security_enabled = True
    manager.security_sensor_entity_ids = ("input_boolean.puerta_negocio_prueba",)
    manager._handle_state_change(
        _event("input_boolean.puerta_negocio_prueba", "off", "on")
    )
    await hass.async_block_till_done()

    assert manager.security_enabled is False
    assert manager.security_sensor_entity_ids == ()
    client.async_get_security_config.assert_not_awaited()
    client.async_send_security_event.assert_not_awaited()
