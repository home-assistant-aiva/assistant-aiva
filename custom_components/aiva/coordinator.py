"""Data coordinator for the AIVA integration."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AivaApiClient, AivaApiError, AivaStatus
from .const import DOMAIN, SYNC_ENTITY_DOMAINS

_LOGGER = logging.getLogger(__name__)


class AivaDataUpdateCoordinator(DataUpdateCoordinator[AivaStatus]):
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

    async def _async_update_data(self) -> AivaStatus:
        """Fetch data from AIVA."""
        try:
            return await self.client.get_status()
        except AivaApiError as err:
            raise UpdateFailed(str(err)) from err

    async def async_retry_connection(self) -> None:
        """Retry the AIVA connection and refresh data."""
        await self.client.heartbeat()
        await self.async_request_refresh()

    async def async_sync_entities(self) -> None:
        """Ask AIVA to synchronize entities and refresh data."""
        await self.client.sync_entities(self._collect_entities())
        await self.async_request_refresh()

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
