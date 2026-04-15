"""API client for the AIVA backend."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urljoin

from aiohttp import ClientError, ClientTimeout

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .const import (
    ACTIVATION_STATES,
    DEFAULT_API_BASE_URL,
    DEFAULT_API_TIMEOUT_SECONDS,
    ENDPOINT_ENTITIES_SYNC,
    ENDPOINT_HEARTBEAT,
    ENDPOINT_PAIR,
    ENDPOINT_PAIRING_START,
    ENDPOINT_PAIRING_STATUS,
    FIELD_ENTITIES,
    FIELD_HEARTBEAT_AT,
    FIELD_HOME_ID,
    FIELD_HOME_NAME,
    FIELD_OK,
    FIELD_PAIRING_CODE,
    FIELD_PLAN,
    FIELD_SECRET,
    FIELD_STATE,
    HEADER_AIVA_SECRET,
    STATE_ACTIVE,
    STATE_AWAITING_PAIRING,
    STATE_AWAITING_PAYMENT,
    STATE_INSTALLED,
)

DISPLAY_STATES = {
    STATE_INSTALLED: "Instalado",
    STATE_AWAITING_PAIRING: "Esperando vinculación",
    STATE_AWAITING_PAYMENT: "Esperando confirmación de pago",
    STATE_ACTIVE: "Activo",
}


class AivaApiError(Exception):
    """Base exception for AIVA API errors."""


AivaError = AivaApiError


class AivaCannotConnectError(AivaApiError):
    """Raised when the AIVA backend cannot be reached."""


class AivaInvalidPairingCodeError(AivaApiError):
    """Raised when the pairing code is invalid."""


class AivaInvalidAuthError(AivaApiError):
    """Raised when stored AIVA credentials are rejected."""


class AivaInvalidResponseError(AivaApiError):
    """Raised when the AIVA backend response is not usable."""


class AivaMissingRequiredDataError(AivaInvalidResponseError):
    """Raised when pairing succeeds without required fields."""


@dataclass(frozen=True, slots=True)
class AivaPairingResult:
    """Data returned by the AIVA pairing endpoint."""

    home_id: str
    secret: str
    home_name: str
    plan: str | None


@dataclass(frozen=True, slots=True)
class AivaActivationStartResult:
    """Data returned when AIVA starts the commercial activation flow."""

    pairing_code: str
    home_name: str
    plan: str
    state: str


@dataclass(frozen=True, slots=True)
class AivaActivationStatus:
    """Current commercial activation status."""

    state: str
    pairing_code: str | None = None
    home_id: str | None = None
    secret: str | None = None
    home_name: str | None = None
    plan: str | None = None


@dataclass(frozen=True, slots=True)
class AivaStatus:
    """Current AIVA status."""

    state: str
    connected: bool
    home_name: str | None
    last_sync: datetime | None


class AivaApiClient:
    """Client used to communicate with the AIVA backend."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        base_url: str = DEFAULT_API_BASE_URL,
        pairing_code: str | None = None,
        home_name: str | None = None,
        home_id: str | None = None,
        secret: str | None = None,
        timeout: int = DEFAULT_API_TIMEOUT_SECONDS,
    ) -> None:
        """Initialize the AIVA API client."""
        self._hass = hass
        self._base_url = base_url.rstrip("/")
        self._pairing_code = (pairing_code or "").strip()
        self._home_name = home_name
        self._home_id = home_id
        self._secret = secret
        self._timeout = timeout
        self._last_sync: datetime | None = None

    async def validate_pairing_code(
        self,
        pairing_code: str,
        home_name: str | None = None,
    ) -> AivaPairingResult:
        """Validate a pairing code against the real AIVA backend."""
        pairing_code = pairing_code.strip()
        if not pairing_code:
            raise AivaInvalidPairingCodeError("El codigo de vinculacion es obligatorio")

        payload = {
            FIELD_PAIRING_CODE: pairing_code,
            FIELD_HOME_NAME: (home_name or "Casa AIVA").strip(),
        }

        data = await self._request("post", ENDPOINT_PAIR, json=payload)
        result = self._parse_pairing_result(data)

        self._pairing_code = pairing_code
        self._home_id = result.home_id
        self._secret = result.secret
        self._home_name = result.home_name

        return result

    async def start_activation(
        self,
        *,
        home_name: str,
        plan: str,
    ) -> AivaActivationStartResult:
        """Ask the backend to generate a pairing code for this installation."""
        payload = {
            FIELD_HOME_NAME: home_name.strip(),
            FIELD_PLAN: plan.strip(),
        }
        data = await self._request("post", ENDPOINT_PAIRING_START, json=payload)
        result = self._parse_activation_start(data, requested_plan=payload[FIELD_PLAN])
        self._pairing_code = result.pairing_code
        self._home_name = result.home_name
        return result

    async def get_activation_status(
        self,
        *,
        pairing_code: str | None = None,
    ) -> AivaActivationStatus:
        """Return the current activation state for a generated pairing code."""
        code = (pairing_code or self._pairing_code).strip()
        if not code:
            raise AivaInvalidPairingCodeError("El codigo de vinculacion es obligatorio")

        data = await self._request(
            "post",
            ENDPOINT_PAIRING_STATUS,
            json={FIELD_PAIRING_CODE: code},
        )
        result = self._parse_activation_status(data)

        if result.state == STATE_ACTIVE:
            if not result.home_id or not result.secret or not result.home_name:
                raise AivaMissingRequiredDataError(
                    "AIVA no devolvio todos los datos de activacion"
                )
            self._home_id = result.home_id
            self._secret = result.secret
            self._home_name = result.home_name

        return result

    async def heartbeat(self) -> dict[str, Any]:
        """Send a heartbeat to the AIVA backend."""
        self._ensure_paired()
        return await self._request(
            "post",
            ENDPOINT_HEARTBEAT,
            json={FIELD_HOME_ID: self._home_id},
            authenticated=True,
        )

    async def get_status(self) -> AivaStatus:
        """Get the current AIVA status.

        The current backend does not expose a dedicated home status endpoint, so
        heartbeat is the source of truth for connectivity.
        """
        data = await self.heartbeat()
        heartbeat_at = data.get(FIELD_HEARTBEAT_AT)
        last_sync = self._last_sync

        if isinstance(heartbeat_at, str):
            last_sync = dt_util.parse_datetime(heartbeat_at) or self._last_sync

        return AivaStatus(
            state=DISPLAY_STATES.get(
                str(data.get(FIELD_STATE) or STATE_ACTIVE),
                "Activo",
            ),
            connected=True,
            home_name=self._home_name,
            last_sync=last_sync,
        )

    async def sync_entities(self, entities: list[dict]) -> dict[str, Any]:
        """Synchronize Home Assistant entities with AIVA."""
        self._ensure_paired()
        data = await self._request(
            "post",
            ENDPOINT_ENTITIES_SYNC,
            json={FIELD_HOME_ID: self._home_id, FIELD_ENTITIES: entities},
            authenticated=True,
        )
        self._last_sync = dt_util.utcnow()
        return data

    async def async_get_status(self) -> AivaStatus:
        """Return the current AIVA status."""
        return await self.get_status()

    async def async_retry_connection(self) -> None:
        """Retry the connection with AIVA."""
        await self.heartbeat()

    async def async_sync_entities(self, entities: list[dict] | None = None) -> None:
        """Synchronize entities with AIVA."""
        await self.sync_entities(entities or [])

    async def _request(
        self,
        method: str,
        endpoint: str,
        *,
        json: dict[str, Any] | None = None,
        authenticated: bool = False,
    ) -> dict[str, Any]:
        """Call the AIVA backend and return a JSON object."""
        session = async_get_clientsession(self._hass)
        url = urljoin(f"{self._base_url}/", endpoint.lstrip("/"))
        headers: dict[str, str] = {}

        if authenticated:
            if not self._secret:
                raise AivaInvalidAuthError("Falta la credencial de AIVA")
            headers[HEADER_AIVA_SECRET] = self._secret

        try:
            async with session.request(
                method,
                url,
                json=json,
                headers=headers,
                timeout=ClientTimeout(total=self._timeout),
            ) as response:
                data = await response.json(content_type=None)
        except TimeoutError as err:
            raise AivaCannotConnectError("Timeout conectando con AIVA") from err
        except ClientError as err:
            raise AivaCannotConnectError("No se pudo conectar con AIVA") from err
        except ValueError as err:
            raise AivaInvalidResponseError("AIVA devolvio una respuesta invalida") from err

        if not isinstance(data, dict):
            raise AivaInvalidResponseError("AIVA devolvio una respuesta invalida")

        if response.status >= 400:
            self._raise_for_error_response(response.status, data)

        if data.get(FIELD_OK) is not True:
            raise AivaInvalidResponseError("AIVA devolvio una respuesta sin ok=true")

        return data

    def _raise_for_error_response(self, status: int, data: dict[str, Any]) -> None:
        """Translate backend error responses into integration exceptions."""
        error = data.get("error")
        code = error.get("code") if isinstance(error, dict) else None

        if code in {
            "expired_pairing_code",
            "invalid_pairing_code",
            "used_pairing_code",
        }:
            raise AivaInvalidPairingCodeError(str(code))

        if code == "invalid_secret" or status == 401:
            raise AivaInvalidAuthError(str(code or "invalid_auth"))

        raise AivaApiError(str(code or f"HTTP {status}"))

    def _parse_pairing_result(self, data: dict[str, Any]) -> AivaPairingResult:
        """Parse and validate the backend pairing response."""
        home_id = data.get(FIELD_HOME_ID)
        secret = data.get(FIELD_SECRET)
        home_name = data.get(FIELD_HOME_NAME)
        plan = data.get(FIELD_PLAN)

        if not isinstance(home_id, str) or not home_id:
            raise AivaMissingRequiredDataError("AIVA no devolvio home_id")
        if not isinstance(secret, str) or not secret:
            raise AivaMissingRequiredDataError("AIVA no devolvio secret")
        if not isinstance(home_name, str) or not home_name:
            raise AivaMissingRequiredDataError("AIVA no devolvio home_name")
        if plan is not None and not isinstance(plan, str):
            raise AivaInvalidResponseError("AIVA devolvio plan invalido")

        return AivaPairingResult(
            home_id=home_id,
            secret=secret,
            home_name=home_name,
            plan=plan,
        )

    def _parse_activation_start(
        self,
        data: dict[str, Any],
        *,
        requested_plan: str,
    ) -> AivaActivationStartResult:
        """Parse the pairing-code generation response."""
        pairing_code = data.get(FIELD_PAIRING_CODE)
        home_name = data.get(FIELD_HOME_NAME)
        plan = data.get(FIELD_PLAN, requested_plan)
        state = data.get(FIELD_STATE, STATE_AWAITING_PAIRING)

        if not isinstance(pairing_code, str) or not pairing_code:
            raise AivaMissingRequiredDataError("AIVA no devolvio pairing_code")
        if not isinstance(home_name, str) or not home_name:
            raise AivaMissingRequiredDataError("AIVA no devolvio home_name")
        if not isinstance(plan, str) or not plan:
            raise AivaInvalidResponseError("AIVA devolvio plan invalido")
        if not isinstance(state, str) or state not in ACTIVATION_STATES:
            raise AivaInvalidResponseError("AIVA devolvio estado invalido")

        return AivaActivationStartResult(
            pairing_code=pairing_code,
            home_name=home_name,
            plan=plan,
            state=state,
        )

    def _parse_activation_status(self, data: dict[str, Any]) -> AivaActivationStatus:
        """Parse the activation status response."""
        state = data.get(FIELD_STATE)
        if not isinstance(state, str) or state not in ACTIVATION_STATES:
            raise AivaInvalidResponseError("AIVA devolvio estado invalido")

        pairing_code = data.get(FIELD_PAIRING_CODE)
        home_id = data.get(FIELD_HOME_ID)
        secret = data.get(FIELD_SECRET)
        home_name = data.get(FIELD_HOME_NAME)
        plan = data.get(FIELD_PLAN)

        for field_name, value in (
            (FIELD_PAIRING_CODE, pairing_code),
            (FIELD_HOME_ID, home_id),
            (FIELD_SECRET, secret),
            (FIELD_HOME_NAME, home_name),
            (FIELD_PLAN, plan),
        ):
            if value is not None and not isinstance(value, str):
                raise AivaInvalidResponseError(f"AIVA devolvio {field_name} invalido")

        return AivaActivationStatus(
            state=state,
            pairing_code=pairing_code,
            home_id=home_id,
            secret=secret,
            home_name=home_name,
            plan=plan,
        )

    def _ensure_paired(self) -> None:
        """Ensure this client has credentials for paired-home endpoints."""
        if not self._home_id or not self._secret:
            raise AivaInvalidAuthError("AIVA no esta vinculado")
