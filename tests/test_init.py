"""Tests for AIVA setup compatibility behavior."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.aiva import async_setup_entry
from custom_components.aiva.const import (
    CONF_BASE_URL,
    CONF_HOME_ID,
    CONF_HOME_NAME,
    CONF_LINKING_CODE,
    CONF_PAIRING_CODE,
    CONF_SECRET,
    DOMAIN,
)


class FakeCoordinator:
    """Coordinator test double."""

    def __init__(self, hass, client, scan_interval_seconds):
        """Initialize the coordinator."""
        self.hass = hass
        self.client = client
        self.scan_interval_seconds = scan_interval_seconds
        self.async_config_entry_first_refresh = AsyncMock()


async def test_setup_entry_reads_legacy_linking_code(hass, monkeypatch):
    """Read linking_code from old entries and store pairing_code going forward."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Casa Principal",
        data={
            CONF_BASE_URL: "http://127.0.0.1:8080",
            CONF_LINKING_CODE: "<legacy-pairing-code>",
            CONF_HOME_ID: "home-1",
            CONF_SECRET: "<redacted-secret>",
            CONF_HOME_NAME: "Casa Principal",
        },
        source=config_entries.SOURCE_USER,
        entry_id="legacy-entry",
        unique_id="home-1",
    )
    entry.add_to_hass(hass)
    monkeypatch.setattr(
        hass.config_entries,
        "async_forward_entry_setups",
        AsyncMock(return_value=True),
    )

    with (
        patch("custom_components.aiva.AivaApiClient") as client_cls,
        patch("custom_components.aiva.AivaDataUpdateCoordinator", FakeCoordinator),
    ):
        client_cls.return_value = object()
        assert await async_setup_entry(hass, entry) is True

    assert client_cls.call_args.kwargs["pairing_code"] == "<legacy-pairing-code>"
    assert entry.data[CONF_PAIRING_CODE] == "<legacy-pairing-code>"
