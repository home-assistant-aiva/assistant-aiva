"""Local execution of non-sensitive actions queued by the AIVA backend."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
import logging
from typing import Any, Callable

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .api import AivaApiClient, AivaApiError
from .const import ACTION_POLL_INTERVAL_SECONDS

_LOGGER = logging.getLogger(__name__)
_RECENT_ACTION_LIMIT = 200
_TURN_DOMAINS = {"light", "switch", "fan", "input_boolean"}
_RUN_DOMAINS = {"scene", "script"}
_BLOCKED_DOMAINS = {"lock", "alarm_control_panel", "cover", "camera", "siren", "vacuum"}


class AivaActionManager:
    """Poll AIVA for actions and execute allowlisted services locally."""

    def __init__(self, hass: HomeAssistant, client: AivaApiClient) -> None:
        """Initialize action processing state."""
        self.hass = hass
        self.client = client
        self.enabled = False
        self.last_action_poll_at: datetime | None = None
        self.last_action_error: str | None = None
        self.processed_action_count = 0
        self._unsub_poll_timer: Callable[[], None] | None = None
        self._poll_task: Any = None
        self._processed: dict[str, tuple[str, str | None, str | None]] = {}
        self._processed_order: deque[str] = deque()

    def async_start(self) -> None:
        """Start lightweight polling after credentials are available."""
        if self._unsub_poll_timer is not None:
            return
        if not getattr(self.client, "home_id", None) or not getattr(self.client, "secret", None):
            return
        self.enabled = True
        self._unsub_poll_timer = async_track_time_interval(
            self.hass,
            self._async_poll_timer,
            timedelta(seconds=ACTION_POLL_INTERVAL_SECONDS),
        )
        self._poll_task = self.hass.async_create_task(self.async_poll_actions())

    def async_stop(self) -> None:
        """Stop polling and any pending initial poll."""
        self.enabled = False
        if self._unsub_poll_timer is not None:
            self._unsub_poll_timer()
            self._unsub_poll_timer = None
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
        self._poll_task = None

    async def async_poll_actions(self) -> None:
        """Fetch pending actions without running any AI/conversation path."""
        self.last_action_poll_at = dt_util.utcnow()
        try:
            actions = await self.client.async_get_pending_actions()
            self.last_action_error = None
        except AivaApiError as err:
            self.last_action_error = err.__class__.__name__
            _LOGGER.warning("AIVA action polling backend error: %s", err)
            return
        for action in actions:
            await self._async_process_action(action)

    async def _async_poll_timer(self, _now: datetime) -> None:
        """Poll from the Home Assistant interval callback."""
        await self.async_poll_actions()

    async def _async_process_action(self, action: dict[str, Any]) -> None:
        action_id = str(action.get("action_id") or "").strip()
        if not action_id:
            return
        previous = self._processed.get(action_id)
        if previous:
            await self._async_report_result(action_id, previous[0], previous[1], previous[2])
            return

        try:
            domain, service, service_data = self._validated_call(action)
            await self.hass.services.async_call(domain, service, service_data, blocking=True)
            status = "completed"
            result_message = "Accion ejecutada localmente."
            error_message = None
        except ValueError as err:
            status = "failed"
            result_message = None
            error_message = str(err)
        except Exception:
            _LOGGER.exception("AIVA local action service call failed: action_id=%s", action_id)
            status = "failed"
            result_message = None
            error_message = "Home Assistant no pudo ejecutar el servicio."

        self._remember_result(action_id, status, result_message, error_message)
        await self._async_report_result(action_id, status, result_message, error_message)

    async def _async_report_result(
        self,
        action_id: str,
        status: str,
        result_message: str | None,
        error_message: str | None,
    ) -> None:
        try:
            await self.client.async_send_action_result(action_id, status, result_message, error_message)
        except AivaApiError as err:
            self.last_action_error = err.__class__.__name__
            _LOGGER.warning("AIVA action result backend error: %s", err)

    def _validated_call(self, action: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
        domain = str(action.get("domain") or "").strip()
        service = str(action.get("service") or "").strip()
        service_data = action.get("service_data")
        if not isinstance(service_data, dict):
            raise ValueError("La accion no incluye service_data valido.")
        entity_id = str(service_data.get("entity_id") or "").strip()
        if not entity_id.startswith(f"{domain}."):
            raise ValueError("La entidad no corresponde al dominio permitido.")
        if domain in _BLOCKED_DOMAINS:
            raise ValueError("Dominio sensible bloqueado por Home Assistant.")
        if domain in _TURN_DOMAINS and service in {"turn_on", "turn_off"}:
            return domain, service, dict(service_data)
        if domain in _RUN_DOMAINS and service == "turn_on":
            return domain, service, dict(service_data)
        if domain == "input_select" and service == "select_option" and isinstance(service_data.get("option"), str):
            return domain, service, dict(service_data)
        raise ValueError("Servicio o dominio no permitido para ejecucion local.")

    def _remember_result(
        self,
        action_id: str,
        status: str,
        result_message: str | None,
        error_message: str | None,
    ) -> None:
        self._processed[action_id] = (status, result_message, error_message)
        self._processed_order.append(action_id)
        self.processed_action_count += 1
        while len(self._processed_order) > _RECENT_ACTION_LIMIT:
            self._processed.pop(self._processed_order.popleft(), None)
