"""AIVA integration for Home Assistant."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

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

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BUTTON]


@dataclass(slots=True)
class AivaRuntimeData:
    """Runtime data stored for an AIVA config entry."""

    client: AivaApiClient
    coordinator: AivaDataUpdateCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up AIVA from a config entry."""
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

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = AivaRuntimeData(
        client=client,
        coordinator=coordinator,
    )

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
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
