"""Diagnostics support for the AIVA integration."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry

from .const import (
    CONF_LINKING_CODE,
    CONF_PAIRING_CODE,
    CONF_SECRET,
    DOMAIN,
    MAX_SUMMARY_ITEMS,
)


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


def _home_settings_diagnostics(settings: Any) -> dict[str, Any] | None:
    """Return safe diagnostics for home settings."""
    if settings is None:
        return None

    return {
        "language": settings.language,
        "assistant_name": settings.assistant_name,
        "country_code": settings.country_code,
        "locale": settings.locale,
        "timezone": settings.timezone,
        "response_style": settings.response_style,
        "custom_prompt_configured": bool(settings.custom_prompt),
    }


def _effective_entities_diagnostics(entities: tuple[Any, ...]) -> dict[str, Any]:
    """Return bounded diagnostics for effective entities."""
    return {
        "total_count": len(entities),
        "allowed_count": sum(entity.is_allowed is True for entity in entities),
        "visible_count": sum(entity.is_visible is True for entity in entities),
        "requires_confirmation_count": sum(
            entity.requires_confirmation is True for entity in entities
        ),
        "sample": [
            {
                "entity_id": entity.entity_id,
                "display_name": entity.display_name,
                "effective_area": entity.effective_area,
                "is_allowed": entity.is_allowed,
                "is_visible": entity.is_visible,
                "requires_confirmation": entity.requires_confirmation,
                "priority": entity.priority,
            }
            for entity in entities[:MAX_SUMMARY_ITEMS]
        ],
    }


def _home_automations_diagnostics(automations: tuple[Any, ...]) -> dict[str, Any]:
    """Return bounded diagnostics for home automations."""
    return {
        "total_count": len(automations),
        "enabled_count": sum(automation.enabled is True for automation in automations),
        "disabled_count": sum(
            automation.enabled is False for automation in automations
        ),
        "sample": [
            {
                "id": automation.automation_id,
                "name": automation.name,
                "enabled": automation.enabled,
            }
            for automation in automations[:MAX_SUMMARY_ITEMS]
        ],
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    runtime_data = hass.data.get(DOMAIN, {}).get(config_entry.entry_id)
    coordinator = getattr(runtime_data, "coordinator", None)
    coordinator_data = getattr(coordinator, "data", None)

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
        "home_settings": _home_settings_diagnostics(
            getattr(coordinator_data, "home_settings", None)
        ),
        "effective_entities": _effective_entities_diagnostics(
            getattr(coordinator_data, "effective_entities", ())
        ),
        "home_automations": _home_automations_diagnostics(
            getattr(coordinator_data, "home_automations", ())
        ),
    }


async def async_get_device_diagnostics(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    device: DeviceEntry,
) -> dict[str, Any]:
    """Return diagnostics for an AIVA device."""
    return await async_get_config_entry_diagnostics(hass, config_entry)
