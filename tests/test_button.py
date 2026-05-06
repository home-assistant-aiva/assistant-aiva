"""Tests for AIVA buttons."""

from __future__ import annotations

from unittest.mock import AsyncMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.aiva.button import AivaButton, BUTTONS
from custom_components.aiva.const import DOMAIN


def _description(key):
    return next(description for description in BUTTONS if description.key == key)


async def test_retry_connection_button_still_calls_manual_reconnect(hass):
    """The manual connection check remains available as a fallback."""
    coordinator = AsyncMock()
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Casa Principal",
        entry_id="test-entry",
        unique_id="home-1",
    )
    button = AivaButton(coordinator, entry, _description("retry_connection"))

    await button.async_press()

    coordinator.async_retry_connection.assert_awaited_once()


async def test_sync_entities_button_still_calls_manual_sync(hass):
    """The manual device update remains available as a fallback."""
    coordinator = AsyncMock()
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Casa Principal",
        entry_id="test-entry",
        unique_id="home-1",
    )
    button = AivaButton(coordinator, entry, _description("sync_entities"))

    await button.async_press()

    coordinator.async_sync_entities.assert_awaited_once()
