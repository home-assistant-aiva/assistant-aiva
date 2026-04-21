"""Data coordinator for the AIVA integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    AivaApiClient,
    AivaApiError,
    AivaEffectiveEntity,
    AivaHomeAutomation,
    AivaHomeSettings,
    AivaStatus,
)
from .const import DOMAIN, SYNC_ENTITY_DOMAINS

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AivaCoordinatorData:
    """Data exposed by the AIVA coordinator."""

    state: str
    connected: bool
    home_name: str | None
    last_sync: datetime | None
    home_settings: AivaHomeSettings | None = None
    effective_entities: tuple[AivaEffectiveEntity, ...] = ()
    home_automations: tuple[AivaHomeAutomation, ...] = ()

    @classmethod
    def from_status(
        cls,
        status: AivaStatus,
        *,
        home_settings: AivaHomeSettings | None = None,
        effective_entities: tuple[AivaEffectiveEntity, ...] = (),
        home_automations: tuple[AivaHomeAutomation, ...] = (),
    ) -> "AivaCoordinatorData":
        """Build enriched coordinator data from the base status."""
        return cls(
            state=status.state,
            connected=status.connected,
            home_name=status.home_name,
            last_sync=status.last_sync,
            home_settings=home_settings,
            effective_entities=effective_entities,
            home_automations=home_automations,
        )


class AivaDataUpdateCoordinator(DataUpdateCoordinator[AivaCoordinatorData]):
    """Coordinate data updates for AIVA."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: AivaApiClient,
        scan_interval_seconds: int,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval_seconds),
        )
        self.client = client

    async def _async_update_data(self) -> AivaCoordinatorData:
        """Fetch data from AIVA."""
        try:
            status = await self.client.get_status()
        except AivaApiError as err:
            raise UpdateFailed(str(err)) from err

        return AivaCoordinatorData.from_status(
            status,
            home_settings=await self._async_load_home_settings(),
            effective_entities=await self._async_load_effective_entities(),
            home_automations=await self._async_load_home_automations(),
        )

    async def async_retry_connection(self) -> None:
        """Retry the AIVA connection and refresh data."""
        await self.client.heartbeat()
        await self.async_request_refresh()

    async def async_sync_entities(self) -> None:
        """Ask AIVA to synchronize entities and refresh data."""
        await self.client.sync_entities(self._collect_entities())
        await self.async_request_refresh()

    async def _async_load_home_settings(self) -> AivaHomeSettings | None:
        """Load optional home settings without failing the base integration."""
        try:
            return await self.client.get_home_settings()
        except AivaApiError as err:
            _LOGGER.debug("No se pudieron cargar settings de AIVA: %s", err)
            return self.data.home_settings if self.data else None

    async def _async_load_effective_entities(self) -> tuple[AivaEffectiveEntity, ...]:
        """Load optional effective entities without failing the base integration."""
        try:
            return await self.client.get_effective_entities()
        except AivaApiError as err:
            _LOGGER.debug("No se pudieron cargar entidades efectivas de AIVA: %s", err)
            return self.data.effective_entities if self.data else ()

    async def _async_load_home_automations(self) -> tuple[AivaHomeAutomation, ...]:
        """Load optional automations without failing the base integration."""
        try:
            return await self.client.get_home_automations()
        except AivaApiError as err:
            _LOGGER.debug("No se pudieron cargar automatizaciones de AIVA: %s", err)
            return self.data.home_automations if self.data else ()

    def _collect_entities(self) -> list[dict]:
        """Build the entity snapshot expected by the AIVA backend."""
        area_registry = ar.async_get(self.hass)
        entity_registry = er.async_get(self.hass)
        entities: list[dict] = []

        for state in self.hass.states.async_all():
            if state.domain not in SYNC_ENTITY_DOMAINS:
                continue

            attributes: dict[str, Any] = dict(state.attributes)
            registry_entry = entity_registry.async_get(state.entity_id)
            area_id = registry_entry.area_id if registry_entry else None
            area_entry = area_registry.async_get_area(area_id) if area_id else None
            area = area_entry.name if area_entry else None

            entities.append(
                {
                    "entity_id": state.entity_id,
                    "domain": state.domain,
                    "friendly_name": state.name,
                    "state": state.state,
                    "area": area,
                    "device_class": attributes.get("device_class"),
                    "unit_of_measurement": attributes.get("unit_of_measurement"),
                    "last_changed": state.last_changed.isoformat(),
                    "last_updated": state.last_updated.isoformat(),
                }
            )

        return entities
