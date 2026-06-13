"""Tests for local queued action execution."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.aiva.actions import AivaActionManager


def _state(state: str = "on"):
    instant = datetime(2026, 5, 26, 1, 47, tzinfo=timezone.utc)
    return SimpleNamespace(
        state=state,
        attributes={
            "friendly_name": "Luz Living Prueba",
            "device_class": "light",
            "icon": "mdi:lightbulb",
            "ignored": "not-sent",
        },
        last_changed=instant,
        last_updated=instant,
    )


def _local_hass(state_obj=None):
    return SimpleNamespace(
        services=SimpleNamespace(async_call=AsyncMock()),
        states=SimpleNamespace(get=Mock(return_value=state_obj)),
    )


def _action(
    domain: str = "input_boolean",
    service: str = "turn_on",
    action_id: str = "action-1",
    lease_id: str = "lease-1",
) -> dict:
    return {
        "action_id": action_id,
        "lease_id": lease_id,
        "domain": domain,
        "service": service,
        "service_data": {"entity_id": f"{domain}.luz_living_prueba"},
    }


@pytest.mark.asyncio
async def test_executes_input_boolean_and_reports_completed(hass):
    """Execute an allowed service locally and acknowledge completion."""
    client = AsyncMock()
    local_hass = _local_hass(_state())
    manager = AivaActionManager(local_hass, client)

    await manager._async_process_action(_action())

    local_hass.services.async_call.assert_awaited_once_with(
        "input_boolean", "turn_on", {"entity_id": "input_boolean.luz_living_prueba"}, blocking=True
    )
    client.async_send_action_result.assert_awaited_once_with(
        "action-1",
        "lease-1",
        "completed",
        "Accion ejecutada localmente.",
        None,
        {
            "entity_id": "input_boolean.luz_living_prueba",
            "state": "on",
            "last_changed": "2026-05-26T01:47:00+00:00",
            "last_updated": "2026-05-26T01:47:00+00:00",
            "attributes": {
                "friendly_name": "Luz Living Prueba",
                "device_class": "light",
                "icon": "mdi:lightbulb",
            },
        },
    )
    local_hass.states.get.assert_called_once_with("input_boolean.luz_living_prueba")
    assert manager.processed_action_count == 1


@pytest.mark.asyncio
async def test_completed_action_without_local_state_is_reported_without_entity_state(hass, caplog):
    """Keep action acknowledgement compatible if the entity vanished after execution."""
    client = AsyncMock()
    local_hass = _local_hass()
    manager = AivaActionManager(local_hass, client)

    with caplog.at_level(logging.WARNING):
        await manager._async_process_action(_action())

    client.async_send_action_result.assert_awaited_once_with(
        "action-1", "lease-1", "completed", "Accion ejecutada localmente.", None, None
    )
    assert "AIVA action final state unavailable" in caplog.text


@pytest.mark.asyncio
async def test_service_failure_reports_failed(hass):
    """Report a safe error if Home Assistant rejects local execution."""
    client = AsyncMock()
    client.secret = "secret-value"
    local_hass = SimpleNamespace(
        services=SimpleNamespace(
            async_call=AsyncMock(
                side_effect=RuntimeError("Invalid service data secret=secret-value detail=bad-domain")
            )
        )
    )
    manager = AivaActionManager(local_hass, client)

    await manager._async_process_action(_action())

    client.async_send_action_result.assert_awaited_once_with(
        "action-1",
        "lease-1",
        "failed",
        None,
        "Home Assistant no pudo ejecutar el servicio: Invalid service data secret=*** detail=bad-domain",
        None,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("domain", ["lock", "alarm_control_panel", "camera", "siren", "vacuum"])
async def test_sensitive_domains_are_blocked_without_execution(hass, domain):
    """Never execute backend actions for sensitive domains."""
    client = AsyncMock()
    local_hass = SimpleNamespace(services=SimpleNamespace(async_call=AsyncMock()))
    manager = AivaActionManager(local_hass, client)

    await manager._async_process_action(_action(domain=domain))

    local_hass.services.async_call.assert_not_awaited()
    assert client.async_send_action_result.await_args.args[2] == "failed"


@pytest.mark.asyncio
async def test_cover_close_cover_is_allowed_for_non_sensitive_curtains(hass):
    """Allow the narrow curtain/persiana close service used by local routines."""
    client = AsyncMock()
    local_hass = _local_hass(_state("closed"))
    manager = AivaActionManager(local_hass, client)

    await manager._async_process_action(_action(domain="cover", service="close_cover"))

    local_hass.services.async_call.assert_awaited_once_with(
        "cover", "close_cover", {"entity_id": "cover.luz_living_prueba"}, blocking=True
    )
    assert client.async_send_action_result.await_args.args[2] == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize("service", ["open_cover", "stop_cover"])
async def test_cover_unsafe_services_remain_blocked(hass, service):
    """Do not allow unsafe cover services from the backend action queue."""
    client = AsyncMock()
    local_hass = _local_hass()
    manager = AivaActionManager(local_hass, client)

    await manager._async_process_action(_action(domain="cover", service=service))

    local_hass.services.async_call.assert_not_awaited()
    assert client.async_send_action_result.await_args.args[2] == "failed"


@pytest.mark.asyncio
async def test_media_player_play_media_allows_aiva_audio_url(hass):
    """Allow Premium Voice playback only for AIVA temporary audio URLs."""
    client = AsyncMock()
    local_hass = _local_hass(_state("playing"))
    manager = AivaActionManager(local_hass, client)
    action = _action(domain="media_player", service="play_media")
    action["service_data"] = {
        "entity_id": "media_player.living",
        "media_content_id": "https://api.aiva.local/premium-voice/audio/non-guessable-id",
        "media_content_type": "music",
        "announce": True,
    }

    await manager._async_process_action(action)

    local_hass.services.async_call.assert_awaited_once_with(
        "media_player",
        "play_media",
        {
            "entity_id": "media_player.living",
            "media_content_id": "https://api.aiva.local/premium-voice/audio/non-guessable-id",
            "media_content_type": "music",
            "announce": True,
        },
        blocking=True,
    )
    assert client.async_send_action_result.await_args.args[2] == "completed"


@pytest.mark.asyncio
async def test_media_player_play_media_blocks_external_url(hass):
    """Do not play arbitrary external media URLs from the backend queue."""
    client = AsyncMock()
    local_hass = _local_hass()
    manager = AivaActionManager(local_hass, client)
    action = _action(domain="media_player", service="play_media")
    action["service_data"] = {
        "entity_id": "media_player.living",
        "media_content_id": "https://example.com/audio.mp3",
        "media_content_type": "music",
    }

    await manager._async_process_action(action)

    local_hass.services.async_call.assert_not_awaited()
    assert client.async_send_action_result.await_args.args[2] == "failed"


@pytest.mark.asyncio
async def test_media_player_other_services_remain_blocked(hass):
    """Keep non-required media_player services blocked."""
    client = AsyncMock()
    local_hass = _local_hass()
    manager = AivaActionManager(local_hass, client)

    await manager._async_process_action(_action(domain="media_player", service="volume_set"))

    local_hass.services.async_call.assert_not_awaited()
    assert client.async_send_action_result.await_args.args[2] == "failed"


@pytest.mark.asyncio
async def test_unlisted_turn_domain_remains_blocked(hass):
    """Only explicitly allowed turn domains can execute local actions."""
    client = AsyncMock()
    local_hass = _local_hass()
    manager = AivaActionManager(local_hass, client)

    await manager._async_process_action(_action(domain="fan", service="turn_on"))

    local_hass.services.async_call.assert_not_awaited()
    assert client.async_send_action_result.await_args.args[2] == "failed"


@pytest.mark.asyncio
async def test_missing_entity_id_is_blocked(hass):
    """Reject actions without a concrete entity_id."""
    client = AsyncMock()
    local_hass = _local_hass()
    manager = AivaActionManager(local_hass, client)
    action = _action(domain="light", service="turn_on")
    action["service_data"].pop("entity_id")

    await manager._async_process_action(action)

    local_hass.services.async_call.assert_not_awaited()
    assert client.async_send_action_result.await_args.args[2] == "failed"


@pytest.mark.asyncio
async def test_input_select_requires_option(hass):
    """Reject input_select actions that do not include a non-empty option."""
    client = AsyncMock()
    local_hass = _local_hass()
    manager = AivaActionManager(local_hass, client)
    action = _action(domain="input_select", service="select_option")
    action["service_data"]["option"] = " "

    await manager._async_process_action(action)

    local_hass.services.async_call.assert_not_awaited()
    assert client.async_send_action_result.await_args.args[2] == "failed"


@pytest.mark.asyncio
async def test_duplicate_action_is_reported_without_second_execution(hass):
    """A retried claim does not execute the local service twice."""
    client = AsyncMock()
    local_hass = _local_hass(_state())
    manager = AivaActionManager(local_hass, client)
    await manager._async_process_action(_action())
    await manager._async_process_action(_action(lease_id="lease-2"))

    local_hass.services.async_call.assert_awaited_once()
    assert client.async_send_action_result.await_count == 2
    assert manager.processed_action_count == 1
    assert client.async_send_action_result.await_args_list[1].args[1] == "lease-2"
    assert client.async_send_action_result.await_args_list[1].args[5]["state"] == "on"


@pytest.mark.asyncio
async def test_action_logs_do_not_expose_home_secret(hass, caplog):
    """Action status logging does not include authentication values."""
    client = AsyncMock()
    client.secret = "<redacted-home-secret>"
    manager = AivaActionManager(_local_hass(_state()), client)

    with caplog.at_level(logging.INFO):
        await manager._async_process_action(_action())

    assert "<redacted-home-secret>" not in caplog.text


@pytest.mark.asyncio
async def test_missing_lease_is_ignored_without_local_execution(hass):
    """Do not execute actions that cannot be acknowledged with a valid lease."""
    client = AsyncMock()
    local_hass = SimpleNamespace(services=SimpleNamespace(async_call=AsyncMock()))
    manager = AivaActionManager(local_hass, client)
    action = _action()
    action.pop("lease_id")

    await manager._async_process_action(action)

    local_hass.services.async_call.assert_not_awaited()
    client.async_send_action_result.assert_not_awaited()
    assert manager.last_action_error == "missing_lease_id"


@pytest.mark.asyncio
async def test_manager_starts_polls_and_stops(hass, monkeypatch):
    """Set up and tear down the lightweight polling task."""
    unsub = Mock()
    tracked = []

    def fake_track(hass_arg, callback, interval):
        tracked.append((hass_arg, callback, interval.total_seconds()))
        return unsub

    monkeypatch.setattr("custom_components.aiva.actions.async_track_time_interval", fake_track)
    client = AsyncMock()
    client.home_id = "home-1"
    client.secret = "<redacted-home-secret>"
    client.async_get_pending_actions.return_value = []
    manager = AivaActionManager(hass, client)

    manager.async_start()
    await hass.async_block_till_done()
    manager.async_stop()

    assert tracked[0][2] == 5
    client.async_get_pending_actions.assert_awaited_once()
    unsub.assert_called_once()
    assert manager.enabled is False
