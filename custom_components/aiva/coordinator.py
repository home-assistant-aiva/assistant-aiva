"""Data coordinator for the AIVA integration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import (
    AivaActivationStatus,
    AivaApiClient,
    AivaApiError,
    AivaBackendServerError,
    AivaCannotConnectError,
    AivaEffectiveEntity,
    AivaHomeAutomation,
    AivaHomeSettings,
    AivaStatus,
)
from .const import (
    DOMAIN,
    EXCLUDED_ENTITY_DOMAINS,
    MAX_SUMMARY_ITEMS,
    STATE_ACTIVE,
    STATE_AWAITING_PAYMENT,
    STATE_ERROR,
    STATE_RECONNECTING,
    STATE_SUSPENDED,
    STATE_UNAVAILABLE,
    SYNC_ENTITY_DOMAINS,
)

_LOGGER = logging.getLogger(__name__)

NOT_EFFECTIVE_STATES = {"unavailable", "unknown"}


@dataclass(frozen=True, slots=True)
class AivaEntitySyncStats:
    """Local Home Assistant entity synchronization summary."""

    total_entities_seen: int = 0
    effective_entities_count: int = 0
    included_domains: tuple[str, ...] = ()
    excluded_domains_count: dict[str, int] | None = None
    sample_effective_entities: tuple[dict[str, Any], ...] = ()
    has_input_boolean: bool = False
    has_input_select: bool = False
    sync_last_error: str | None = None


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
    entity_sync: AivaEntitySyncStats = field(default_factory=AivaEntitySyncStats)
    activation_state: str | None = None
    reconnect_state: str = STATE_RECONNECTING

    @classmethod
    def from_status(
        cls,
        status: AivaStatus,
        *,
        home_settings: AivaHomeSettings | None = None,
        effective_entities: tuple[AivaEffectiveEntity, ...] = (),
        home_automations: tuple[AivaHomeAutomation, ...] = (),
        entity_sync: AivaEntitySyncStats | None = None,
        activation_state: str | None = None,
        reconnect_state: str | None = None,
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
            entity_sync=entity_sync or AivaEntitySyncStats(),
            activation_state=activation_state,
            reconnect_state=(
                reconnect_state
                or (STATE_ACTIVE if status.connected else STATE_RECONNECTING)
            ),
        )

    @classmethod
    def reconnecting(
        cls,
        *,
        home_name: str | None,
        previous: "AivaCoordinatorData | None" = None,
        error: str | None = None,
    ) -> "AivaCoordinatorData":
        """Build data for a safe startup or retrying state."""
        entity_sync = previous.entity_sync if previous else AivaEntitySyncStats(
            sync_last_error=error
        )
        if previous and error:
            entity_sync = AivaEntitySyncStats(
                total_entities_seen=previous.entity_sync.total_entities_seen,
                effective_entities_count=previous.entity_sync.effective_entities_count,
                included_domains=previous.entity_sync.included_domains,
                excluded_domains_count=previous.entity_sync.excluded_domains_count,
                sample_effective_entities=previous.entity_sync.sample_effective_entities,
                has_input_boolean=previous.entity_sync.has_input_boolean,
                has_input_select=previous.entity_sync.has_input_select,
                sync_last_error=error,
            )
        return cls(
            state=STATE_RECONNECTING,
            connected=False,
            home_name=home_name or (previous.home_name if previous else None),
            last_sync=previous.last_sync if previous else None,
            home_settings=previous.home_settings if previous else None,
            effective_entities=previous.effective_entities if previous else (),
            home_automations=previous.home_automations if previous else (),
            entity_sync=entity_sync,
            activation_state=previous.activation_state if previous else None,
            reconnect_state=STATE_RECONNECTING,
        )

    @classmethod
    def unavailable(
        cls,
        *,
        home_name: str | None,
        previous: "AivaCoordinatorData | None" = None,
        error: str | None = None,
        state: str = STATE_UNAVAILABLE,
    ) -> "AivaCoordinatorData":
        """Build data for an unreachable backend without losing cached details."""
        data = cls.reconnecting(home_name=home_name, previous=previous, error=error)
        return cls(
            state=state,
            connected=False,
            home_name=data.home_name,
            last_sync=data.last_sync,
            home_settings=data.home_settings,
            effective_entities=data.effective_entities,
            home_automations=data.home_automations,
            entity_sync=data.entity_sync,
            activation_state=data.activation_state,
            reconnect_state=state,
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
        self._last_entity_sync_stats = AivaEntitySyncStats()
        self._sync_last_error: str | None = None
        self._reconnect_lock = asyncio.Lock()
        self._reconnect_task: asyncio.Task[None] | None = None
        self._unsub_reconnect_retry: Any = None
        self._next_reconnect_at: datetime | None = None
        self._reconnect_failures = 0
        self.reconnect_state = STATE_RECONNECTING
        self.activation_state: str | None = None
        self.last_reconnect_attempt_at: datetime | None = None
        self.last_reconnect_success_at: datetime | None = None
        self.last_heartbeat_success_at: datetime | None = None
        self.last_heartbeat_error: str | None = None
        self.last_sync_success_at: datetime | None = None
        self.last_sync_error: str | None = None

        self.async_set_updated_data(
            AivaCoordinatorData.reconnecting(home_name=self._client_home_name())
        )

    async def _async_update_data(self) -> AivaCoordinatorData:
        """Fetch data from AIVA."""
        try:
            status = await self.client.get_status()
            self._mark_heartbeat_success()
            activation_status = await self._async_get_activation_status()
        except AivaApiError as err:
            self._mark_connection_failure(err)
            return AivaCoordinatorData.unavailable(
                home_name=self._client_home_name(),
                previous=self.data,
                error=str(err),
                state=self.reconnect_state,
            )

        status = self._status_with_activation(status, activation_status)
        data = AivaCoordinatorData.from_status(
            status,
            home_settings=await self._async_load_home_settings(),
            effective_entities=await self._async_load_effective_entities(),
            home_automations=await self._async_load_home_automations(),
            entity_sync=self._snapshot_entity_sync_stats(),
            activation_state=self.activation_state,
            reconnect_state=self.reconnect_state,
        )
        return data

    async def async_retry_connection(self) -> None:
        """Retry the AIVA connection and refresh data."""
        await self.async_reconnect(reason="manual")

    async def async_sync_entities(self) -> None:
        """Ask AIVA to synchronize entities and refresh data."""
        entities = self._collect_entities()
        try:
            await self.client.sync_entities(entities)
        except AivaApiError as err:
            self._sync_last_error = str(err)
            self.last_sync_error = str(err)
            self._last_entity_sync_stats = self._last_entity_sync_stats_with_error(err)
            _LOGGER.warning(
                "No se pudieron sincronizar entidades con AIVA: %s",
                err,
            )
            await self.async_request_refresh()
            return

        self._sync_last_error = None
        self.last_sync_error = None
        self.last_sync_success_at = _utcnow()
        self._last_entity_sync_stats = self._last_entity_sync_stats_with_error(None)
        _LOGGER.info(
            "Entidades sincronizadas con AIVA: total=%s efectivas=%s dominios=%s",
            self._last_entity_sync_stats.total_entities_seen,
            self._last_entity_sync_stats.effective_entities_count,
            ", ".join(self._last_entity_sync_stats.included_domains) or "ninguno",
        )
        await self.async_request_refresh()

    def async_start_auto_reconnect(self) -> None:
        """Start the low-frequency retry loop used while AIVA is unavailable."""
        if self._unsub_reconnect_retry is not None:
            return

        self._unsub_reconnect_retry = async_track_time_interval(
            self.hass,
            self._async_retry_timer,
            timedelta(seconds=30),
        )

    def async_stop_auto_reconnect(self) -> None:
        """Stop retry timers and pending background reconnect work."""
        if self._unsub_reconnect_retry is not None:
            self._unsub_reconnect_retry()
            self._unsub_reconnect_retry = None
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
        self._reconnect_task = None

    def async_schedule_reconnect(self, *, reason: str) -> None:
        """Schedule a reconnect attempt without duplicating concurrent work."""
        if self._reconnect_task and not self._reconnect_task.done():
            return
        self._reconnect_task = self.hass.async_create_task(
            self.async_reconnect(reason=reason)
        )

    async def async_reconnect(self, *, reason: str) -> None:
        """Reconnect to AIVA, verify activation, and sync entities if active."""
        async with self._reconnect_lock:
            self.last_reconnect_attempt_at = _utcnow()
            self.reconnect_state = STATE_RECONNECTING
            self.async_set_updated_data(
                AivaCoordinatorData.reconnecting(
                    home_name=self._client_home_name(),
                    previous=self.data,
                )
            )

            try:
                await self.client.heartbeat()
                self._mark_heartbeat_success()
                activation_status = await self._async_get_activation_status()
                status = await self.client.get_status()
                self._mark_heartbeat_success()
            except AivaApiError as err:
                self._mark_connection_failure(err)
                self._schedule_next_retry()
                self.async_set_updated_data(
                    AivaCoordinatorData.unavailable(
                        home_name=self._client_home_name(),
                        previous=self.data,
                        error=str(err),
                        state=self.reconnect_state,
                    )
                )
                if self._reconnect_failures in {1, 3, 6}:
                    _LOGGER.warning(
                        "AIVA no pudo reconectar (%s). Se reintentará automáticamente: %s",
                        reason,
                        err,
                    )
                return

            status = self._status_with_activation(status, activation_status)
            self.last_reconnect_success_at = _utcnow()
            self.reconnect_state = (
                STATE_ACTIVE
                if status.connected
                else (self.activation_state or STATE_ERROR)
            )
            self._reconnect_failures = 0
            self._next_reconnect_at = None

            self.async_set_updated_data(
                AivaCoordinatorData.from_status(
                    status,
                    home_settings=await self._async_load_home_settings(),
                    effective_entities=await self._async_load_effective_entities(),
                    home_automations=await self._async_load_home_automations(),
                    entity_sync=self._snapshot_entity_sync_stats(),
                    activation_state=self.activation_state,
                    reconnect_state=self.reconnect_state,
                )
            )

            if status.connected:
                await self.async_sync_entities()

    async def _async_retry_timer(self, _now: datetime) -> None:
        """Retry reconnects using a simple backoff while disconnected."""
        if self.data and self.data.connected:
            return
        if self._reconnect_task and not self._reconnect_task.done():
            return
        now = _utcnow()
        if self._next_reconnect_at and now < self._next_reconnect_at:
            return
        self.async_schedule_reconnect(reason="retry")

    async def _async_get_activation_status(self) -> AivaActivationStatus | None:
        """Load activation status and keep diagnostics updated."""
        activation_status = await self.client.get_activation_status()
        if not isinstance(activation_status, AivaActivationStatus):
            return None
        self.activation_state = activation_status.state
        return activation_status

    def _status_with_activation(
        self,
        status: AivaStatus,
        activation_status: AivaActivationStatus | None,
    ) -> AivaStatus:
        """Resolve user-visible status from heartbeat and activation state."""
        if activation_status is None:
            self.reconnect_state = (
                STATE_ACTIVE if status.connected else STATE_UNAVAILABLE
            )
            return status

        activation_state = activation_status.state
        home_name = (
            activation_status.home_name
            or status.home_name
            or self._client_home_name()
        )
        if activation_state == STATE_ACTIVE:
            self.reconnect_state = STATE_ACTIVE
            return AivaStatus(
                state=STATE_ACTIVE,
                connected=status.connected,
                home_name=home_name,
                last_sync=status.last_sync,
            )
        if activation_state in {STATE_AWAITING_PAYMENT, STATE_SUSPENDED}:
            self.reconnect_state = activation_state
            return AivaStatus(
                state=activation_state,
                connected=False,
                home_name=home_name,
                last_sync=status.last_sync,
            )

        self.reconnect_state = activation_state
        return AivaStatus(
            state=activation_state,
            connected=False,
            home_name=home_name,
            last_sync=status.last_sync,
        )

    def _mark_heartbeat_success(self) -> None:
        """Record a successful heartbeat without exposing credentials."""
        self.last_heartbeat_success_at = _utcnow()
        self.last_heartbeat_error = None

    def _mark_connection_failure(self, err: Exception) -> None:
        """Record a failed reconnect/heartbeat attempt."""
        self.last_heartbeat_error = str(err)
        self.reconnect_state = (
            STATE_UNAVAILABLE
            if isinstance(err, (AivaCannotConnectError, AivaBackendServerError))
            else STATE_ERROR
        )
        self._reconnect_failures += 1

    def _schedule_next_retry(self) -> None:
        """Schedule the next reconnect using a bounded simple backoff."""
        delay = 30 if self._reconnect_failures <= 6 else 120
        self._next_reconnect_at = _utcnow() + timedelta(seconds=delay)

    def _client_home_name(self) -> str | None:
        """Return a concrete client home name if available."""
        home_name = getattr(self.client, "home_name", None)
        return home_name if isinstance(home_name, str) and home_name else None

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
        device_registry = dr.async_get(self.hass)
        entity_registry = er.async_get(self.hass)
        entities: list[dict] = []
        included_domains: set[str] = set()
        excluded_domains_count: dict[str, int] = {}
        sample_effective_entities: list[dict[str, Any]] = []
        effective_entities_count = 0
        total_entities_seen = 0

        for state in self.hass.states.async_all():
            total_entities_seen += 1
            registry_entry = entity_registry.async_get(state.entity_id)

            if self._is_aiva_entity(state.entity_id, registry_entry):
                excluded_domains_count[state.domain] = (
                    excluded_domains_count.get(state.domain, 0) + 1
                )
                continue

            if state.domain not in SYNC_ENTITY_DOMAINS:
                excluded_domains_count[state.domain] = (
                    excluded_domains_count.get(state.domain, 0) + 1
                )
                continue

            attributes: dict[str, Any] = dict(state.attributes)
            area_id = registry_entry.area_id if registry_entry else None
            if not area_id and registry_entry and registry_entry.device_id:
                device_entry = device_registry.async_get(registry_entry.device_id)
                area_id = device_entry.area_id if device_entry else None
            area_entry = area_registry.async_get_area(area_id) if area_id else None
            area = area_entry.name if area_entry else None
            friendly_name = (
                state.name or attributes.get("friendly_name") or state.entity_id
            )
            is_available = state.state not in NOT_EFFECTIVE_STATES
            is_effective = is_available
            included_domains.add(state.domain)

            entity_payload: dict[str, Any] = {
                "entity_id": state.entity_id,
                "domain": state.domain,
                "friendly_name": friendly_name,
                "state": state.state,
                "area": area,
                "device_class": attributes.get("device_class"),
                "icon": attributes.get("icon"),
                "unit_of_measurement": attributes.get("unit_of_measurement"),
                "last_changed": state.last_changed.isoformat(),
                "last_updated": state.last_updated.isoformat(),
                "supported_features": attributes.get("supported_features"),
                "available": is_available,
                "effective": is_effective,
            }
            if state.domain == "input_select":
                entity_payload["options"] = attributes.get("options")
            aliases = attributes.get("aliases")
            if isinstance(aliases, list):
                entity_payload["aliases"] = [
                    alias for alias in aliases if isinstance(alias, str)
                ]

            entities.append(entity_payload)

            if is_effective:
                effective_entities_count += 1
                if len(sample_effective_entities) < MAX_SUMMARY_ITEMS:
                    sample_effective_entities.append(
                        {
                            "entity_id": state.entity_id,
                            "domain": state.domain,
                            "friendly_name": friendly_name,
                            "area": area,
                            "state": state.state,
                        }
                    )

        self._last_entity_sync_stats = AivaEntitySyncStats(
            total_entities_seen=total_entities_seen,
            effective_entities_count=effective_entities_count,
            included_domains=tuple(sorted(included_domains)),
            excluded_domains_count={
                domain: excluded_domains_count[domain]
                for domain in sorted(excluded_domains_count)
                if domain not in SYNC_ENTITY_DOMAINS
                or domain in EXCLUDED_ENTITY_DOMAINS
            },
            sample_effective_entities=tuple(sample_effective_entities),
            has_input_boolean="input_boolean" in included_domains,
            has_input_select="input_select" in included_domains,
            sync_last_error=self._sync_last_error,
        )
        return entities

    def _snapshot_entity_sync_stats(self) -> AivaEntitySyncStats:
        """Refresh and return local entity sync stats without contacting AIVA."""
        self._collect_entities()
        return self._last_entity_sync_stats

    def _last_entity_sync_stats_with_error(
        self,
        err: Exception | None,
    ) -> AivaEntitySyncStats:
        """Return the latest sync stats with the last sync error attached."""
        stats = self._last_entity_sync_stats
        return AivaEntitySyncStats(
            total_entities_seen=stats.total_entities_seen,
            effective_entities_count=stats.effective_entities_count,
            included_domains=stats.included_domains,
            excluded_domains_count=stats.excluded_domains_count,
            sample_effective_entities=stats.sample_effective_entities,
            has_input_boolean=stats.has_input_boolean,
            has_input_select=stats.has_input_select,
            sync_last_error=str(err) if err else None,
        )

    @staticmethod
    def _is_aiva_entity(entity_id: str, registry_entry: Any) -> bool:
        """Return true for AIVA's own entities."""
        if entity_id.startswith(("sensor.aiva_", "button.aiva_")):
            return True

        return getattr(registry_entry, "platform", None) == DOMAIN


def _utcnow() -> datetime:
    """Return an aware UTC timestamp for diagnostics."""
    return datetime.now(timezone.utc)
