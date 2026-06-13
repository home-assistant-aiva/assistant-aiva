"""Local execution of non-sensitive actions queued by the AIVA backend."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
import logging
import re
from typing import Any, Callable

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .api import AivaApiClient, AivaApiError
from .const import ACTION_POLL_INTERVAL_SECONDS

_LOGGER = logging.getLogger(__name__)
_RECENT_ACTION_LIMIT = 200
_PROCESSED_TTL = timedelta(minutes=10)
_TURN_DOMAINS = {"light", "switch", "input_boolean"}
_RUN_DOMAINS = {"scene", "script"}
_BLOCKED_DOMAINS = {"lock", "alarm_control_panel", "camera", "siren", "vacuum"}
_AIVA_AUDIO_PATH_PART = "/premium-voice/audio/"
_SENSITIVE_TEXT_PATTERN = re.compile(
    r"(?i)\b(secret|pairing_code|linking_code|token|api[_-]?key|authorization|password)\b\s*[:=]\s*[^,\s]+"
)


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
        self._processed: dict[str, tuple[datetime, str, str | None, str | None, dict[str, Any] | None]] = {}
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
        _LOGGER.info(
            "AIVA action received: action_id=%s domain=%s service=%s",
            action_id,
            action.get("domain"),
            action.get("service"),
        )
        lease_id = str(action.get("lease_id") or "").strip()
        if not lease_id:
            self.last_action_error = "missing_lease_id"
            _LOGGER.warning("AIVA action ignored because lease_id is missing: action_id=%s", action_id)
            return
        self._purge_expired_processed()
        previous = self._processed.get(action_id)
        if previous:
            await self._async_report_result(action_id, lease_id, previous[1], previous[2], previous[3], previous[4])
            return

        entity_state: dict[str, Any] | None = None
        try:
            domain, service, service_data = self._validated_call(action)
            await self.hass.services.async_call(domain, service, service_data, blocking=True)
            status = "completed"
            result_message = "Accion ejecutada localmente."
            error_message = None
            entity_state = self._read_final_entity_state(action_id, service_data["entity_id"])
            _LOGGER.info("AIVA action executed: action_id=%s", action_id)
        except ValueError as err:
            status = "failed"
            result_message = None
            error_message = str(err)
            _LOGGER.warning("AIVA action failed: action_id=%s error=%s", action_id, error_message)
        except Exception as err:
            safe_error = self._safe_home_assistant_error(err)
            _LOGGER.exception("AIVA action failed: action_id=%s error=%s", action_id, safe_error)
            status = "failed"
            result_message = None
            error_message = f"Home Assistant no pudo ejecutar el servicio: {safe_error}"

        self._remember_result(action_id, status, result_message, error_message, entity_state)
        await self._async_report_result(action_id, lease_id, status, result_message, error_message, entity_state)

    def _read_final_entity_state(self, action_id: str, entity_id: str) -> dict[str, Any] | None:
        """Read a safe entity snapshot after local action execution."""
        state_obj = self.hass.states.get(entity_id)
        if state_obj is None:
            _LOGGER.warning(
                "AIVA action final state unavailable: action_id=%s entity_id=%s",
                action_id,
                entity_id,
            )
            return None
        attributes = {
            key: state_obj.attributes[key]
            for key in ("friendly_name", "device_class", "icon")
            if key in state_obj.attributes
        }
        _LOGGER.info(
            "AIVA action final state read: action_id=%s entity_id=%s state=%s",
            action_id,
            entity_id,
            state_obj.state,
        )
        return {
            "entity_id": entity_id,
            "state": state_obj.state,
            "last_changed": state_obj.last_changed.isoformat(),
            "last_updated": state_obj.last_updated.isoformat(),
            "attributes": attributes,
        }

    async def _async_report_result(
        self,
        action_id: str,
        lease_id: str,
        status: str,
        result_message: str | None,
        error_message: str | None,
        entity_state: dict[str, Any] | None,
    ) -> None:
        try:
            await self.client.async_send_action_result(
                action_id, lease_id, status, result_message, error_message, entity_state
            )
            if entity_state is not None:
                _LOGGER.info(
                    "AIVA action result reported with entity_state: action_id=%s status=%s entity_id=%s",
                    action_id,
                    status,
                    entity_state["entity_id"],
                )
            else:
                _LOGGER.info("AIVA action result reported: action_id=%s status=%s", action_id, status)
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
        if domain == "media_player" and service == "play_media":
            return domain, service, self._validated_media_player_play_media(service_data)
        option = service_data.get("option")
        if domain == "input_select" and service == "select_option" and isinstance(option, str) and option.strip():
            return domain, service, dict(service_data)
        if domain == "cover" and service == "close_cover":
            return domain, service, dict(service_data)
        raise ValueError("Servicio o dominio no permitido para ejecucion local.")

    def _validated_media_player_play_media(self, service_data: dict[str, Any]) -> dict[str, Any]:
        entity_id = str(service_data.get("entity_id") or "").strip()
        media_content_id = str(service_data.get("media_content_id") or "").strip()
        media_content_type = str(service_data.get("media_content_type") or "").strip()
        if not entity_id.startswith("media_player."):
            raise ValueError("La entidad media_player no es valida.")
        if not self._is_aiva_audio_url(media_content_id):
            raise ValueError("URL de audio externa bloqueada.")
        if media_content_type not in {"music", "audio/mpeg"}:
            raise ValueError("Tipo de audio no permitido.")
        validated = {
            "entity_id": entity_id,
            "media_content_id": media_content_id,
            "media_content_type": media_content_type,
        }
        if service_data.get("announce") is not None:
            validated["announce"] = bool(service_data.get("announce"))
        return validated

    def _is_aiva_audio_url(self, value: str) -> bool:
        if not value.startswith(("http://", "https://")):
            return False
        if _AIVA_AUDIO_PATH_PART not in value:
            return False
        lowered = value.lower()
        return not any(part in lowered for part in ("token=", "api_key=", "authorization=", "@"))

    def _safe_home_assistant_error(self, err: Exception) -> str:
        """Return a useful Home Assistant error without leaking credentials."""
        message = str(err).strip() or err.__class__.__name__
        message = _SENSITIVE_TEXT_PATTERN.sub(r"\1=***", message)
        for value in (getattr(self.client, "secret", None), getattr(self.client, "home_id", None)):
            if isinstance(value, str) and value:
                message = message.replace(value, "***")
        if len(message) > 300:
            message = f"{message[:297]}..."
        return message

    def _remember_result(
        self,
        action_id: str,
        status: str,
        result_message: str | None,
        error_message: str | None,
        entity_state: dict[str, Any] | None,
    ) -> None:
        self._processed[action_id] = (dt_util.utcnow(), status, result_message, error_message, entity_state)
        self._processed_order.append(action_id)
        self.processed_action_count += 1
        while len(self._processed_order) > _RECENT_ACTION_LIMIT:
            self._processed.pop(self._processed_order.popleft(), None)

    def _purge_expired_processed(self) -> None:
        cutoff = dt_util.utcnow() - _PROCESSED_TTL
        while self._processed_order:
            action_id = self._processed_order[0]
            processed = self._processed.get(action_id)
            if processed is not None and processed[0] > cutoff:
                break
            self._processed_order.popleft()
            self._processed.pop(action_id, None)
