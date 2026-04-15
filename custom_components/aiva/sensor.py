"""Sensor entities for the AIVA integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTR_CONNECTED, ATTR_HOME_NAME, DOMAIN
from .coordinator import AivaDataUpdateCoordinator


@dataclass(frozen=True, kw_only=True)
class AivaSensorEntityDescription(SensorEntityDescription):
    """Description for an AIVA sensor."""

    value_fn: Callable[[AivaDataUpdateCoordinator], Any]


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
            return None

        return {
            ATTR_CONNECTED: self.coordinator.data.connected,
            ATTR_HOME_NAME: self.coordinator.data.home_name,
        }
