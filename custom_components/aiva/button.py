"""Button entities for the AIVA integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AivaDataUpdateCoordinator


@dataclass(frozen=True, kw_only=True)
class AivaButtonEntityDescription(ButtonEntityDescription):
    """Description for an AIVA button."""

    press_fn: Callable[[AivaDataUpdateCoordinator], Awaitable[None]]


BUTTONS: tuple[AivaButtonEntityDescription, ...] = (
    AivaButtonEntityDescription(
        key="retry_connection",
        translation_key="retry_connection",
        press_fn=lambda coordinator: coordinator.async_retry_connection(),
    ),
    AivaButtonEntityDescription(
        key="sync_entities",
        translation_key="sync_entities",
        press_fn=lambda coordinator: coordinator.async_sync_entities(),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up AIVA buttons."""
    runtime_data = hass.data[DOMAIN][entry.entry_id]
    coordinator = runtime_data.coordinator

    async_add_entities(
        AivaButton(coordinator, entry, description) for description in BUTTONS
    )


class AivaButton(CoordinatorEntity[AivaDataUpdateCoordinator], ButtonEntity):
    """AIVA button entity."""

    entity_description: AivaButtonEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: AivaDataUpdateCoordinator,
        entry: ConfigEntry,
        description: AivaButtonEntityDescription,
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title,
            "manufacturer": "AIVA",
        }

    async def async_press(self) -> None:
        """Handle the button press."""
        await self.entity_description.press_fn(self.coordinator)
