"""Diagnostics support for the AIVA integration."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry

from .const import CONF_LINKING_CODE, CONF_PAIRING_CODE, CONF_SECRET, DOMAIN


def _mask_pairing_code(value: Any) -> Any:
    """Return a safe representation of a pairing code."""
    if not isinstance(value, str) or len(value) <= 4:
        return "**REDACTED**"

    return f"{value[:4]}...**REDACTED**"


def _redact_sensitive_data(data: dict[str, Any]) -> dict[str, Any]:
    """Redact sensitive values from diagnostics data."""
    redacted = dict(data)

    if CONF_SECRET in redacted:
        redacted[CONF_SECRET] = "**REDACTED**"
    if CONF_PAIRING_CODE in redacted:
        redacted[CONF_PAIRING_CODE] = _mask_pairing_code(redacted[CONF_PAIRING_CODE])
    if CONF_LINKING_CODE in redacted:
        redacted[CONF_LINKING_CODE] = _mask_pairing_code(redacted[CONF_LINKING_CODE])

    return redacted


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    runtime_data = hass.data.get(DOMAIN, {}).get(config_entry.entry_id)
    coordinator = getattr(runtime_data, "coordinator", None)

    return {
        "entry": {
            "title": config_entry.title,
            "data": _redact_sensitive_data(config_entry.data),
            "options": _redact_sensitive_data(config_entry.options),
        },
        "coordinator": {
            "last_update_success": getattr(coordinator, "last_update_success", None),
            "update_interval": (
                coordinator.update_interval.total_seconds()
                if coordinator and coordinator.update_interval
                else None
            ),
        },
    }


async def async_get_device_diagnostics(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    device: DeviceEntry,
) -> dict[str, Any]:
    """Return diagnostics for an AIVA device."""
    return await async_get_config_entry_diagnostics(hass, config_entry)
