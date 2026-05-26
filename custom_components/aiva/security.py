"""AIVA Seguridad Negocios support."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any, Callable

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from .api import AivaActivationStatus, AivaApiClient, AivaApiError
from .const import STATE_ACTIVE

_LOGGER = logging.getLogger(__name__)

IGNORED_STATES = {"unknown", "unavailable"}
SECURITY_CONFIG_REFRESH_SECONDS = 60


class AivaSecurityManager:
    """Load AIVA security config and forward configured sensor events."""

    def __init__(self, hass: HomeAssistant, client: AivaApiClient) -> None:
        """Initialize the security manager."""
        self.hass = hass
        self.client = client
        self.security_enabled = False
        self.security_sensor_entity_ids: tuple[str, ...] = ()
        self.last_security_config_update: datetime | None = None
        self._unsub_state_listener: Callable[[], None] | None = None
        self._unsub_refresh_timer: Callable[[], None] | None = None
        self._refresh_task: Any = None

    def async_start(self) -> None:
        """Start periodic security config refresh."""
        if self._unsub_refresh_timer is not None:
            return

        self._unsub_refresh_timer = async_track_time_interval(
            self.hass,
            self._async_refresh_timer,
            timedelta(seconds=SECURITY_CONFIG_REFRESH_SECONDS),
        )
        self._refresh_task = self.hass.async_create_task(self.async_refresh_config())

    def async_stop(self) -> None:
        """Stop timers and state listeners."""
        if self._unsub_refresh_timer is not None:
            self._unsub_refresh_timer()
            self._unsub_refresh_timer = None
        if self._refresh_task and not self._refresh_task.done():
            self._refresh_task.cancel()
        self._refresh_task = None
        self._clear_state_listener()

    async def async_refresh_config(self) -> None:
        """Load security config and update state listeners."""
        if not await self._async_home_is_active():
            self._disable_security()
            return

        try:
            config = await self.client.async_get_security_config(
                self.client.home_id,
                self.client.secret,
            )
        except AivaApiError as err:
            _LOGGER.warning("AIVA security backend error: %s", err)
            return

        self.security_enabled = config.security_enabled
        self.last_security_config_update = dt_util.utcnow()

        if not config.security_enabled:
            _LOGGER.info("AIVA security disabled for this home")
            self._disable_security()
            return

        active_entity_ids = tuple(
            sorted(
                {
                    sensor.entity_id
                    for sensor in config.sensors
                    if sensor.is_active and sensor.entity_id
                }
            )
        )
        _LOGGER.info("AIVA security config loaded")
        _LOGGER.info("AIVA security sensors configured: %s", len(active_entity_ids))

        if not active_entity_ids:
            self.security_sensor_entity_ids = ()
            self._clear_state_listener()
            return

        if active_entity_ids == self.security_sensor_entity_ids:
            return

        self._clear_state_listener()
        self.security_sensor_entity_ids = active_entity_ids
        self._unsub_state_listener = async_track_state_change_event(
            self.hass,
            active_entity_ids,
            self._handle_state_change,
        )

    async def _async_refresh_timer(self, _now: datetime) -> None:
        """Refresh config from the periodic timer."""
        await self.async_refresh_config()

    @callback
    def _handle_state_change(self, event: Event) -> None:
        """Handle a Home Assistant state change for configured sensors."""
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")
        if old_state is None or new_state is None:
            return

        old_value = old_state.state
        new_value = new_state.state
        entity_id = new_state.entity_id

        if old_value == new_value:
            return
        if new_value is None or new_value in IGNORED_STATES:
            _LOGGER.info("AIVA security event ignored: unavailable/unknown")
            return
        if not self.security_enabled or entity_id not in self.security_sensor_entity_ids:
            return

        event_time = dt_util.now().isoformat(timespec="seconds")
        self.hass.async_create_task(
            self._async_send_event(entity_id, new_value, event_time)
        )

    async def _async_send_event(
        self,
        entity_id: str,
        state: str,
        event_time: str,
    ) -> None:
        """Send a state-change event to the backend."""
        if not await self._async_home_is_active():
            self._disable_security()
            return

        try:
            await self.client.async_send_security_event(
                self.client.home_id,
                self.client.secret,
                entity_id,
                state,
                event_time,
            )
        except AivaApiError as err:
            _LOGGER.warning("AIVA security backend error: %s", err)
            return

        _LOGGER.info(
            "AIVA security event sent: entity_id=%s, state=%s",
            entity_id,
            state,
        )

    async def _async_home_is_active(self) -> bool:
        """Return whether the shared home activation currently permits security."""
        try:
            status = await self.client.get_activation_status()
        except AivaApiError as err:
            _LOGGER.warning("AIVA security could not confirm activation: %s", err)
            return False

        if isinstance(status, AivaActivationStatus) and status.state == STATE_ACTIVE:
            return True

        activation_state = (
            status.state if isinstance(status, AivaActivationStatus) else "unknown"
        )
        _LOGGER.info(
            "AIVA security waiting for home activation: activation_state=%s",
            activation_state,
        )
        return False

    def _disable_security(self) -> None:
        """Prevent listeners and events while security cannot run."""
        self.security_enabled = False
        self.security_sensor_entity_ids = ()
        self._clear_state_listener()

    def _clear_state_listener(self) -> None:
        """Unregister current state listener if present."""
        if self._unsub_state_listener is None:
            return
        self._unsub_state_listener()
        self._unsub_state_listener = None
