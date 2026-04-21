"""Sensor entities for the AIVA integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_ALLOWED_COUNT,
    ATTR_ASSISTANT_NAME,
    ATTR_CONNECTED,
    ATTR_COUNTRY_CODE,
    ATTR_CUSTOM_PROMPT_CONFIGURED,
    ATTR_DISABLED_COUNT,
    ATTR_ENABLED_COUNT,
    ATTR_HOME_NAME,
    ATTR_LANGUAGE,
    ATTR_LOCALE,
    ATTR_REQUIRES_CONFIRMATION_COUNT,
    ATTR_RESPONSE_STYLE,
    ATTR_SAMPLE,
    ATTR_TIMEZONE,
    ATTR_TOTAL_COUNT,
    ATTR_VISIBLE_COUNT,
    DOMAIN,
    MAX_SUMMARY_ITEMS,
)
from .coordinator import AivaDataUpdateCoordinator


@dataclass(frozen=True, kw_only=True)
class AivaSensorEntityDescription(SensorEntityDescription):
    """Description for an AIVA sensor."""

    value_fn: Callable[[AivaDataUpdateCoordinator], Any]
    attributes_fn: Callable[[AivaDataUpdateCoordinator], dict[str, Any] | None] = (
        lambda coordinator: None
    )


def _settings_value(coordinator: AivaDataUpdateCoordinator) -> str | None:
    """Return a compact settings state."""
    settings = coordinator.data.home_settings
    if settings is None:
        return None

    return settings.assistant_name or settings.language or "Configurado"


def _settings_attributes(
    coordinator: AivaDataUpdateCoordinator,
) -> dict[str, Any] | None:
    """Return safe home settings attributes."""
    settings = coordinator.data.home_settings
    if settings is None:
        return None

    return {
        ATTR_LANGUAGE: settings.language,
        ATTR_ASSISTANT_NAME: settings.assistant_name,
        ATTR_COUNTRY_CODE: settings.country_code,
        ATTR_LOCALE: settings.locale,
        ATTR_TIMEZONE: settings.timezone,
        ATTR_RESPONSE_STYLE: settings.response_style,
        ATTR_CUSTOM_PROMPT_CONFIGURED: bool(settings.custom_prompt),
    }


def _effective_entities_attributes(
    coordinator: AivaDataUpdateCoordinator,
) -> dict[str, Any]:
    """Return compact effective entity counts and a small sample."""
    entities = coordinator.data.effective_entities
    return {
        ATTR_TOTAL_COUNT: len(entities),
        ATTR_ALLOWED_COUNT: sum(entity.is_allowed is True for entity in entities),
        ATTR_VISIBLE_COUNT: sum(entity.is_visible is True for entity in entities),
        ATTR_REQUIRES_CONFIRMATION_COUNT: sum(
            entity.requires_confirmation is True for entity in entities
        ),
        ATTR_SAMPLE: [
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


def _home_automations_attributes(
    coordinator: AivaDataUpdateCoordinator,
) -> dict[str, Any]:
    """Return compact automation counts and a small sample."""
    automations = coordinator.data.home_automations
    return {
        ATTR_TOTAL_COUNT: len(automations),
        ATTR_ENABLED_COUNT: sum(
            automation.enabled is True for automation in automations
        ),
        ATTR_DISABLED_COUNT: sum(
            automation.enabled is False for automation in automations
        ),
        ATTR_SAMPLE: [
            {
                "id": automation.automation_id,
                "name": automation.name,
                "enabled": automation.enabled,
            }
            for automation in automations[:MAX_SUMMARY_ITEMS]
        ],
    }


SENSORS: tuple[AivaSensorEntityDescription, ...] = (
    AivaSensorEntityDescription(
        key="status",
        translation_key="status",
        value_fn=lambda coordinator: coordinator.data.state,
    ),
    AivaSensorEntityDescription(
        key="last_sync",
        translation_key="last_sync",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda coordinator: coordinator.data.last_sync,
    ),
    AivaSensorEntityDescription(
        key="home_settings",
        translation_key="home_settings",
        value_fn=_settings_value,
        attributes_fn=_settings_attributes,
    ),
    AivaSensorEntityDescription(
        key="effective_entities",
        translation_key="effective_entities",
        value_fn=lambda coordinator: len(coordinator.data.effective_entities),
        attributes_fn=_effective_entities_attributes,
    ),
    AivaSensorEntityDescription(
        key="home_automations",
        translation_key="home_automations",
        value_fn=lambda coordinator: len(coordinator.data.home_automations),
        attributes_fn=_home_automations_attributes,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up AIVA sensors."""
    runtime_data = hass.data[DOMAIN][entry.entry_id]
    coordinator = runtime_data.coordinator

    async_add_entities(
        AivaSensor(coordinator, entry, description) for description in SENSORS
    )


class AivaSensor(CoordinatorEntity[AivaDataUpdateCoordinator], SensorEntity):
    """AIVA sensor entity."""

    entity_description: AivaSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: AivaDataUpdateCoordinator,
        entry: ConfigEntry,
        description: AivaSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title,
            "manufacturer": "AIVA",
        }

    @property
    def native_value(self) -> Any:
        """Return the sensor state."""
        return self.entity_description.value_fn(self.coordinator)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        if self.entity_description.key != "status":
            return self.entity_description.attributes_fn(self.coordinator)

        return {
            ATTR_CONNECTED: self.coordinator.data.connected,
            ATTR_HOME_NAME: self.coordinator.data.home_name,
        }
