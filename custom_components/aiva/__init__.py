"""AIVA integration for Home Assistant."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, Platform
from homeassistant.core import Event, HomeAssistant

from .api import AivaApiClient
from .const import (
    CONF_BASE_URL,
    CONF_HOME_ID,
    CONF_HOME_NAME,
    CONF_LINKING_CODE,
    CONF_PAIRING_CODE,
    CONF_SCAN_INTERVAL,
    CONF_SECRET,
    DEFAULT_API_BASE_URL,
    DEFAULT_SCAN_INTERVAL_SECONDS,
    DOMAIN,
    MIN_SCAN_INTERVAL_SECONDS,
)
from .coordinator import AivaDataUpdateCoordinator
from .version import get_integration_version

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BUTTON, Platform.CONVERSATION]
_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class AivaRuntimeData:
    """Runtime data stored for an AIVA config entry."""

    client: AivaApiClient
    coordinator: AivaDataUpdateCoordinator
    integration_version: str
    conversation_entity_id: str | None = "conversation.aiva"
    conversation_last_request_at: datetime | None = None
    conversation_last_error: str | None = None
    conversation_backend_status: str | None = None


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up AIVA from a config entry."""
    integration_version = get_integration_version()
    pairing_code = entry.data.get(CONF_PAIRING_CODE, entry.data.get(CONF_LINKING_CODE))
    if CONF_PAIRING_CODE not in entry.data and pairing_code:
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, CONF_PAIRING_CODE: pairing_code},
        )

    base_url = entry.options.get(CONF_BASE_URL, entry.data.get(CONF_BASE_URL))
    scan_interval = entry.options.get(
        CONF_SCAN_INTERVAL,
        DEFAULT_SCAN_INTERVAL_SECONDS,
    )
    scan_interval = max(int(scan_interval), MIN_SCAN_INTERVAL_SECONDS)

    client = AivaApiClient(
        hass=hass,
        base_url=base_url or DEFAULT_API_BASE_URL,
        pairing_code=pairing_code,
        home_name=entry.data.get(CONF_HOME_NAME),
        home_id=entry.data.get(CONF_HOME_ID),
        secret=entry.data.get(CONF_SECRET),
    )
    coordinator = AivaDataUpdateCoordinator(hass, client, scan_interval)
    coordinator.async_start_auto_reconnect()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = AivaRuntimeData(
        client=client,
        coordinator=coordinator,
        integration_version=integration_version,
    )

    _LOGGER.info(
        "Cargando integración AIVA version %s para '%s'",
        integration_version,
        entry.title,
    )

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    entry.async_on_unload(coordinator.async_stop_auto_reconnect)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    coordinator.async_schedule_reconnect(reason="setup")
    entry.async_on_unload(
        hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STARTED,
            _schedule_started_reconnect(coordinator),
        )
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an AIVA config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload AIVA when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


def _schedule_started_reconnect(
    coordinator: AivaDataUpdateCoordinator,
):
    """Return a HA-started callback that schedules one reconnect attempt."""

    def _handle_started(_event: Event) -> None:
        coordinator.async_schedule_reconnect(reason="homeassistant_started")

    return _handle_started
