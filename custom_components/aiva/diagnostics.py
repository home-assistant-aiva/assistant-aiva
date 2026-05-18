"""Diagnostics support for the AIVA integration."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit, urlunsplit

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
from .version import get_integration_version


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


def _entity_sync_diagnostics(stats: Any) -> dict[str, Any]:
    """Return safe diagnostics for the local entity sync snapshot."""
    return {
        "total_entities_seen": getattr(stats, "total_entities_seen", 0),
        "effective_entities_count": getattr(stats, "effective_entities_count", 0),
        "included_domains": list(getattr(stats, "included_domains", ())),
        "excluded_domains_count": getattr(stats, "excluded_domains_count", None) or {},
        "sample_effective_entities": list(
            getattr(stats, "sample_effective_entities", ())
        )[:MAX_SUMMARY_ITEMS],
        "has_input_boolean": getattr(stats, "has_input_boolean", False),
        "has_input_select": getattr(stats, "has_input_select", False),
        "sync_last_error": getattr(stats, "sync_last_error", None),
    }


def _safe_datetime(value: Any) -> str | None:
    """Return a safe ISO timestamp for diagnostics."""
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    return isoformat() if callable(isoformat) else str(value)


def _sanitize_base_url(value: Any) -> str | None:
    """Return backend base_url without credentials, query, or fragment."""
    if not isinstance(value, str) or not value:
        return None
    parts = urlsplit(value)
    netloc = parts.hostname or ""
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path.rstrip("/"), "", ""))


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
    integration_version = getattr(
        runtime_data,
        "integration_version",
        get_integration_version(),
    )
    coordinator = getattr(runtime_data, "coordinator", None)
    security_manager = getattr(runtime_data, "security_manager", None)
    client = getattr(runtime_data, "client", None)
    coordinator_data = getattr(coordinator, "data", None)
    entity_sync = getattr(coordinator_data, "entity_sync", None)

    return {
        "integration": {
            "domain": DOMAIN,
            "version": integration_version,
        },
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
            "reconnect_state": getattr(coordinator, "reconnect_state", None),
            "last_reconnect_attempt_at": _safe_datetime(
                getattr(coordinator, "last_reconnect_attempt_at", None)
            ),
            "last_reconnect_success_at": _safe_datetime(
                getattr(coordinator, "last_reconnect_success_at", None)
            ),
            "last_heartbeat_success_at": _safe_datetime(
                getattr(coordinator, "last_heartbeat_success_at", None)
            ),
            "last_heartbeat_error": getattr(coordinator, "last_heartbeat_error", None),
            "last_sync_success_at": _safe_datetime(
                getattr(coordinator, "last_sync_success_at", None)
            ),
            "last_sync_error": getattr(coordinator, "last_sync_error", None),
            "backend_base_url": _sanitize_base_url(
                getattr(client, "base_url", config_entry.data.get("base_url"))
            ),
            "activation_state": getattr(coordinator, "activation_state", None),
            "effective_entities_count": getattr(
                entity_sync,
                "effective_entities_count",
                None,
            ),
        },
        "conversation": {
            "conversation_agent_enabled": runtime_data is not None,
            "conversation_entity_id": getattr(
                runtime_data,
                "conversation_entity_id",
                "conversation.aiva" if runtime_data is not None else None,
            ),
            "conversation_last_request_at": _safe_datetime(
                getattr(runtime_data, "conversation_last_request_at", None)
            ),
            "conversation_last_error": getattr(
                runtime_data,
                "conversation_last_error",
                None,
            ),
            "conversation_backend_status": getattr(
                runtime_data,
                "conversation_backend_status",
                None,
            ),
        },
        "security": {
            "security_enabled": getattr(
                security_manager,
                "security_enabled",
                False,
            ),
            "security_sensor_count": len(
                getattr(security_manager, "security_sensor_entity_ids", ())
            ),
            "security_sensor_entity_ids": list(
                getattr(security_manager, "security_sensor_entity_ids", ())
            ),
            "last_security_config_update": _safe_datetime(
                getattr(security_manager, "last_security_config_update", None)
            ),
        },
        "home_settings": _home_settings_diagnostics(
            getattr(coordinator_data, "home_settings", None)
        ),
        "effective_entities": _effective_entities_diagnostics(
            getattr(coordinator_data, "effective_entities", ())
        ),
        "entity_sync": _entity_sync_diagnostics(entity_sync),
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
