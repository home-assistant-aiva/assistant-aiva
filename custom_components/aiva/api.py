"""API client for the AIVA backend."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json as json_module
import logging
from typing import Any
from urllib.parse import urljoin

from aiohttp import ClientError, ClientTimeout

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.instance_id import async_get as async_get_instance_id
from homeassistant.util import dt as dt_util

from .const import (
    ACTIVATION_STATES,
    DEFAULT_API_BASE_URL,
    DEFAULT_API_TIMEOUT_SECONDS,
    ENDPOINT_ACTIVATION_PAIRING_CODE,
    ENDPOINT_ACTIVATION_REQUEST,
    ENDPOINT_ACTIVATION_STATUS,
    ENDPOINT_ENTITIES_EFFECTIVE,
    ENDPOINT_ENTITIES_SYNC,
    ENDPOINT_HEARTBEAT,
    ENDPOINT_HOME_AUTOMATIONS,
    ENDPOINT_HOME_SETTINGS,
    ENDPOINT_PAIR,
    ENDPOINT_PAIRING_START,
    FIELD_ACTIVATION_STATE,
    FIELD_AUTOMATIONS,
    FIELD_ENTITIES,
    FIELD_EFFECTIVE_ENTITIES,
    FIELD_HEARTBEAT_AT,
    FIELD_HOME_AUTOMATIONS,
    FIELD_HOME_ID,
    FIELD_HOME_NAME,
    FIELD_HOME_SETTINGS,
    FIELD_INSTALLATION_ID,
    FIELD_OK,
    FIELD_PAIRING_CODE,
    FIELD_PLAN,
    FIELD_SECRET,
    FIELD_SETTINGS,
    FIELD_STATE,
    HEADER_AIVA_SECRET,
    STATE_ACTIVE,
    STATE_AWAITING_PAIRING,
    STATE_AWAITING_PAYMENT,
    STATE_INSTALLED,
)

_LOGGER = logging.getLogger(__name__)

DISPLAY_STATES = {
    STATE_INSTALLED: "Instalado",
    STATE_AWAITING_PAIRING: "Esperando vinculación",
    STATE_AWAITING_PAYMENT: "Esperando confirmación de pago",
    STATE_ACTIVE: "Activo",
}


class AivaApiError(Exception):
    """Base exception for AIVA API errors."""

    def __init__(
        self,
        message: str,
        *,
        user_message: str | None = None,
        status: int | None = None,
        endpoint: str | None = None,
        url: str | None = None,
        response_body: str | None = None,
        request_id: str | None = None,
        error_code: str | None = None,
    ) -> None:
        """Initialize the exception with backend diagnostics."""
        super().__init__(message)
        self.user_message = user_message or message
        self.status = status
        self.endpoint = endpoint
        self.url = url
        self.response_body = response_body
        self.request_id = request_id
        self.error_code = error_code


AivaError = AivaApiError


class AivaCannotConnectError(AivaApiError):
    """Raised when the AIVA backend cannot be reached."""


class AivaTimeoutError(AivaCannotConnectError):
    """Raised when the AIVA backend request times out."""


class AivaConnectionError(AivaCannotConnectError):
    """Raised when the AIVA backend connection fails."""


class AivaInvalidPairingCodeError(AivaApiError):
    """Raised when the pairing code is invalid."""


class AivaInvalidAuthError(AivaApiError):
    """Raised when stored AIVA credentials are rejected."""


class AivaInvalidResponseError(AivaApiError):
    """Raised when the AIVA backend response is not usable."""


class AivaMissingRequiredDataError(AivaInvalidResponseError):
    """Raised when pairing succeeds without required fields."""


class AivaBackendClientError(AivaApiError):
    """Raised when the backend returns a 4xx response."""


class AivaBackendServerError(AivaApiError):
    """Raised when the backend returns a 5xx response."""


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
    home_id: str | None = None
    secret: str | None = None


@dataclass(frozen=True, slots=True)
class AivaActivationRequestResult:
    """Data returned by the initial activation request."""

    home_name: str
    plan: str
    state: str
    home_id: str | None = None
    secret: str | None = None
    pairing_code: str | None = None


@dataclass(frozen=True, slots=True)
class AivaPairingCodeResult:
    """Data returned by the pairing-code generation endpoint."""

    pairing_code: str
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


@dataclass(frozen=True, slots=True)
class AivaHomeSettings:
    """AIVA home-level settings returned by the backend."""

    language: str | None = None
    assistant_name: str | None = None
    voice_provider: str | None = None
    voice_id: str | None = None
    custom_prompt: str | None = None
    country_code: str | None = None
    locale: str | None = None
    timezone: str | None = None
    response_style: str | None = None


@dataclass(frozen=True, slots=True)
class AivaEffectiveEntity:
    """Entity metadata after backend defaults and customizations are merged."""

    entity_id: str
    display_name: str | None = None
    effective_area: str | None = None
    alias: str | None = None
    area_override: str | None = None
    is_allowed: bool | None = None
    is_visible: bool | None = None
    requires_confirmation: bool | None = None
    priority: int | None = None


@dataclass(frozen=True, slots=True)
class AivaHomeAutomation:
    """AIVA automation summary returned by the backend."""

    automation_id: str
    name: str | None = None
    enabled: bool | None = None
    raw: dict[str, Any] | None = None


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
        self._base_url = self.normalize_base_url(base_url)
        self._pairing_code = (pairing_code or "").strip()
        self._home_name = home_name
        self._home_id = home_id
        self._secret = secret
        self._timeout = timeout
        self._last_sync: datetime | None = None

    @staticmethod
    def normalize_base_url(base_url: str) -> str:
        """Normalize a backend base URL for relative endpoint joins."""
        return base_url.strip().rstrip("/")

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
        """Start activation and obtain the pairing code using the backend flow."""
        installation_id = await self._get_installation_id()
        payload = {
            FIELD_INSTALLATION_ID: installation_id,
            FIELD_HOME_NAME: home_name.strip(),
            FIELD_PLAN: plan.strip(),
        }
        try:
            data = await self._request("post", ENDPOINT_ACTIVATION_REQUEST, json=payload)
        except AivaBackendClientError as err:
            if err.status not in {404, 405}:
                raise
            _LOGGER.warning(
                "AIVA backend rejected %s with HTTP %s; retrying legacy endpoint %s",
                ENDPOINT_ACTIVATION_REQUEST,
                err.status,
                ENDPOINT_PAIRING_START,
            )
            data = await self._request("post", ENDPOINT_PAIRING_START, json=payload)
            result = self._parse_legacy_activation_start(
                data,
                requested_plan=payload[FIELD_PLAN],
            )
            self._pairing_code = result.pairing_code
            self._home_name = result.home_name
            return result

        activation = self._parse_activation_request(
            data,
            requested_plan=payload[FIELD_PLAN],
        )
        self._home_id = activation.home_id
        self._secret = activation.secret
        self._home_name = activation.home_name

        _LOGGER.debug(
            "AIVA activation request parsed: endpoint=%s installation_id=%s state=%s home_id=%s home_name=%s plan=%s pairing_code=%s",
            ENDPOINT_ACTIVATION_REQUEST,
            self._mask_token(installation_id),
            activation.state,
            self._mask_token(activation.home_id) if activation.home_id else None,
            activation.home_name,
            activation.plan,
            self._mask_token(activation.pairing_code) if activation.pairing_code else None,
        )

        if activation.pairing_code:
            self._pairing_code = activation.pairing_code
            return AivaActivationStartResult(
                pairing_code=activation.pairing_code,
                home_name=activation.home_name,
                plan=activation.plan,
                state=activation.state,
                home_id=activation.home_id,
                secret=activation.secret,
            )

        if not activation.home_id or not activation.secret:
            raise AivaMissingRequiredDataError(
                "AIVA no devolvio home_id o secret para generar el codigo de vinculacion",
                user_message=(
                    "AIVA respondió que la instalación está lista, pero no envió "
                    "los datos necesarios para generar el código de vinculación."
                ),
                endpoint=ENDPOINT_ACTIVATION_REQUEST,
            )

        pairing = await self.generate_pairing_code(
            home_id=activation.home_id,
            secret=activation.secret,
        )
        self._pairing_code = pairing.pairing_code

        return AivaActivationStartResult(
            pairing_code=pairing.pairing_code,
            home_name=activation.home_name,
            plan=activation.plan,
            state=(
                activation.state
                if activation.state != STATE_INSTALLED
                and pairing.state == STATE_AWAITING_PAIRING
                else pairing.state
            ),
            home_id=activation.home_id,
            secret=activation.secret,
        )

    async def generate_pairing_code(
        self,
        *,
        home_id: str | None = None,
        secret: str | None = None,
    ) -> AivaPairingCodeResult:
        """Generate a pairing code after activation/request succeeded."""
        resolved_home_id = (home_id or self._home_id or "").strip()
        resolved_secret = (secret or self._secret or "").strip()
        if not resolved_home_id:
            raise AivaMissingRequiredDataError(
                "AIVA no devolvio home_id para generar el codigo de vinculacion",
                user_message=(
                    "AIVA no envió el identificador del hogar necesario para "
                    "generar el código de vinculación."
                ),
                endpoint=ENDPOINT_ACTIVATION_PAIRING_CODE,
            )
        if not resolved_secret:
            raise AivaMissingRequiredDataError(
                "AIVA no devolvio secret para generar el codigo de vinculacion",
                user_message=(
                    "AIVA no envió la credencial necesaria para generar el "
                    "código de vinculación."
                ),
                endpoint=ENDPOINT_ACTIVATION_PAIRING_CODE,
            )

        self._home_id = resolved_home_id
        self._secret = resolved_secret
        data = await self._request(
            "post",
            ENDPOINT_ACTIVATION_PAIRING_CODE,
            json={FIELD_HOME_ID: resolved_home_id},
            authenticated=True,
        )
        result = self._parse_pairing_code_generation(data)
        _LOGGER.debug(
            "AIVA pairing code parsed: endpoint=%s state=%s home_id=%s pairing_code=%s",
            ENDPOINT_ACTIVATION_PAIRING_CODE,
            result.state,
            self._mask_token(resolved_home_id),
            self._mask_token(result.pairing_code),
        )
        return result

    async def get_activation_status(
        self,
        *,
        home_id: str | None = None,
        secret: str | None = None,
    ) -> AivaActivationStatus:
        """Return the current activation state for a home."""
        resolved_home_id = (home_id or self._home_id or "").strip()
        resolved_secret = (secret or self._secret or "").strip()
        if not resolved_home_id:
            raise AivaMissingRequiredDataError("AIVA no devolvio home_id")
        if not resolved_secret:
            raise AivaMissingRequiredDataError("AIVA no devolvio secret")

        self._home_id = resolved_home_id
        self._secret = resolved_secret

        data = await self._request(
            "get",
            ENDPOINT_ACTIVATION_STATUS,
            params={FIELD_HOME_ID: resolved_home_id},
            authenticated=True,
        )
        result = self._parse_activation_status(data)
        _LOGGER.debug(
            "AIVA activation status parsed: endpoint=%s state=%s "
            "home_id=%s response_home_id=%s",
            ENDPOINT_ACTIVATION_STATUS,
            result.state,
            self._mask_token(resolved_home_id),
            self._mask_token(result.home_id) if result.home_id else None,
        )

        if result.home_id is None:
            result = AivaActivationStatus(
                state=result.state,
                pairing_code=result.pairing_code,
                home_id=resolved_home_id,
                secret=result.secret,
                home_name=result.home_name,
                plan=result.plan,
            )
        if result.secret is None:
            result = AivaActivationStatus(
                state=result.state,
                pairing_code=result.pairing_code,
                home_id=result.home_id,
                secret=resolved_secret,
                home_name=result.home_name,
                plan=result.plan,
            )
        if result.home_name is None and self._home_name:
            result = AivaActivationStatus(
                state=result.state,
                pairing_code=result.pairing_code,
                home_id=result.home_id,
                secret=result.secret,
                home_name=self._home_name,
                plan=result.plan,
            )

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

    async def get_home_settings(self) -> AivaHomeSettings:
        """Return home settings from AIVA."""
        self._ensure_paired()
        data = await self._request(
            "get",
            ENDPOINT_HOME_SETTINGS,
            authenticated=True,
        )
        return self._parse_home_settings(data)

    async def get_effective_entities(self) -> tuple[AivaEffectiveEntity, ...]:
        """Return backend-enriched entity metadata."""
        self._ensure_paired()
        data = await self._request(
            "get",
            ENDPOINT_ENTITIES_EFFECTIVE,
            authenticated=True,
        )
        return self._parse_effective_entities(data)

    async def get_home_automations(self) -> tuple[AivaHomeAutomation, ...]:
        """Return AIVA home automations."""
        self._ensure_paired()
        data = await self._request(
            "get",
            ENDPOINT_HOME_AUTOMATIONS,
            authenticated=True,
        )
        return self._parse_home_automations(data)

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
        params: dict[str, Any] | None = None,
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

        _LOGGER.debug(
            "AIVA request starting: method=%s base_url=%s endpoint=%s url=%s "
            "params=%s payload=%s headers=%s",
            method.upper(),
            self._base_url,
            endpoint,
            url,
            self._sanitize_for_log(params),
            self._sanitize_for_log(json),
            self._sanitize_for_log(headers),
        )

        try:
            async with session.request(
                method,
                url,
                params=params,
                json=json,
                headers=headers,
                timeout=ClientTimeout(total=self._timeout),
            ) as response:
                response_text = await response.text()
                request_id = response.headers.get("x-request-id") or response.headers.get(
                    "X-Request-ID"
                )
                sanitized_body = self._sanitize_text_for_log(response_text)
                _LOGGER.debug(
                    "AIVA response received: method=%s url=%s endpoint=%s status=%s request_id=%s body=%s",
                    method.upper(),
                    url,
                    endpoint,
                    response.status,
                    request_id,
                    sanitized_body,
                )
        except TimeoutError as err:
            _LOGGER.exception(
                "AIVA request timed out: method=%s url=%s endpoint=%s",
                method.upper(),
                url,
                endpoint,
            )
            raise AivaTimeoutError(
                "Timeout conectando con AIVA",
                user_message="AIVA tardó demasiado en responder. Verificá la dirección e intentá nuevamente.",
                endpoint=endpoint,
                url=url,
            ) from err
        except ClientError as err:
            _LOGGER.exception(
                "AIVA request failed due to connection error: method=%s url=%s endpoint=%s error=%s",
                method.upper(),
                url,
                endpoint,
                err,
            )
            raise AivaConnectionError(
                "No se pudo conectar con AIVA",
                user_message="No se pudo conectar con AIVA. Revisá la dirección de conexión e intentá nuevamente.",
                endpoint=endpoint,
                url=url,
            ) from err

        try:
            data = json_module.loads(response_text)
        except ValueError as err:
            _LOGGER.error(
                "AIVA returned a non-JSON or malformed response: method=%s url=%s endpoint=%s status=%s request_id=%s body=%s",
                method.upper(),
                url,
                endpoint,
                response.status,
                request_id,
                sanitized_body,
            )
            raise AivaInvalidResponseError(
                "AIVA devolvio una respuesta invalida",
                user_message="AIVA devolvió una respuesta inválida. Revisá los logs para más detalle.",
                status=response.status,
                endpoint=endpoint,
                url=url,
                response_body=sanitized_body,
                request_id=request_id,
            ) from err

        if not isinstance(data, dict):
            raise AivaInvalidResponseError(
                "AIVA devolvio una respuesta invalida",
                user_message="AIVA devolvió una respuesta inválida. Revisá los logs para más detalle.",
                status=response.status,
                endpoint=endpoint,
                url=url,
                response_body=sanitized_body,
                request_id=request_id,
            )

        if response.status >= 400:
            self._raise_for_error_response(
                response.status,
                data,
                endpoint=endpoint,
                url=url,
                response_body=sanitized_body,
                request_id=request_id,
            )

        if data.get(FIELD_OK) is not True:
            raise AivaInvalidResponseError(
                "AIVA devolvio una respuesta sin ok=true",
                user_message=(
                    self._extract_backend_message(data)
                    or "AIVA respondió sin confirmar la operación."
                ),
                status=response.status,
                endpoint=endpoint,
                url=url,
                response_body=sanitized_body,
                request_id=request_id,
            )

        return data

    def _raise_for_error_response(
        self,
        status: int,
        data: dict[str, Any],
        *,
        endpoint: str,
        url: str,
        response_body: str,
        request_id: str | None,
    ) -> None:
        """Translate backend error responses into integration exceptions."""
        error = data.get("error")
        code = error.get("code") if isinstance(error, dict) else None
        backend_message = self._extract_backend_message(data)

        _LOGGER.warning(
            "AIVA backend returned HTTP error: status=%s endpoint=%s url=%s request_id=%s code=%s body=%s",
            status,
            endpoint,
            url,
            request_id,
            code,
            response_body,
        )

        if code in {
            "expired_pairing_code",
            "invalid_pairing_code",
            "used_pairing_code",
        }:
            raise AivaInvalidPairingCodeError(
                str(code),
                user_message=backend_message
                or "El código de vinculación no es válido o ya venció.",
                status=status,
                endpoint=endpoint,
                url=url,
                response_body=response_body,
                request_id=request_id,
                error_code=code,
            )

        if code == "invalid_secret" or status == 401:
            raise AivaInvalidAuthError(
                str(code or "invalid_auth"),
                user_message=backend_message
                or "Las credenciales de AIVA fueron rechazadas por el backend.",
                status=status,
                endpoint=endpoint,
                url=url,
                response_body=response_body,
                request_id=request_id,
                error_code=code,
            )

        error_cls = AivaBackendServerError if status >= 500 else AivaBackendClientError
        default_message = (
            "AIVA respondió con un error interno. Intentá nuevamente en unos minutos."
            if status >= 500
            else "AIVA rechazó la solicitud. Revisá los datos ingresados e intentá nuevamente."
        )
        raise error_cls(
            str(code or f"HTTP {status}"),
            user_message=backend_message or default_message,
            status=status,
            endpoint=endpoint,
            url=url,
            response_body=response_body,
            request_id=request_id,
            error_code=code,
        )

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

    def _parse_activation_request(
        self,
        data: dict[str, Any],
        *,
        requested_plan: str,
    ) -> AivaActivationRequestResult:
        """Parse the initial activation request response."""
        home_id = data.get(FIELD_HOME_ID)
        secret = data.get(FIELD_SECRET)
        pairing_code = data.get(FIELD_PAIRING_CODE)
        home_name = data.get(FIELD_HOME_NAME)
        plan = self._resolve_activation_plan(
            data.get(FIELD_PLAN),
            requested_plan=requested_plan,
            endpoint=ENDPOINT_ACTIVATION_REQUEST,
        )
        state = self._extract_activation_state(data, default=STATE_INSTALLED)

        if not isinstance(home_name, str) or not home_name:
            raise AivaMissingRequiredDataError("AIVA no devolvio home_name")
        for field_name, value in (
            (FIELD_HOME_ID, home_id),
            (FIELD_SECRET, secret),
            (FIELD_PAIRING_CODE, pairing_code),
        ):
            if value is not None and (not isinstance(value, str) or not value):
                raise AivaInvalidResponseError(f"AIVA devolvio {field_name} invalido")

        return AivaActivationRequestResult(
            home_name=home_name,
            plan=plan,
            state=state,
            home_id=home_id,
            secret=secret,
            pairing_code=pairing_code,
        )

    def _parse_legacy_activation_start(
        self,
        data: dict[str, Any],
        *,
        requested_plan: str,
    ) -> AivaActivationStartResult:
        """Parse the legacy endpoint that already returns pairing_code."""
        pairing_code = data.get(FIELD_PAIRING_CODE)
        home_name = data.get(FIELD_HOME_NAME)
        plan = self._resolve_activation_plan(
            data.get(FIELD_PLAN),
            requested_plan=requested_plan,
            endpoint=ENDPOINT_PAIRING_START,
        )
        state = self._extract_activation_state(data, default=STATE_AWAITING_PAIRING)

        if not isinstance(pairing_code, str) or not pairing_code:
            raise AivaMissingRequiredDataError("AIVA no devolvio pairing_code")
        if not isinstance(home_name, str) or not home_name:
            raise AivaMissingRequiredDataError("AIVA no devolvio home_name")

        return AivaActivationStartResult(
            pairing_code=pairing_code,
            home_name=home_name,
            plan=plan,
            state=state,
        )

    def _parse_pairing_code_generation(
        self,
        data: dict[str, Any],
    ) -> AivaPairingCodeResult:
        """Parse the pairing-code generation response."""
        pairing_code = data.get(FIELD_PAIRING_CODE)
        state = self._extract_activation_state(data, default=STATE_AWAITING_PAIRING)

        if not isinstance(pairing_code, str) or not pairing_code:
            raise AivaMissingRequiredDataError(
                "AIVA no devolvio pairing_code",
                user_message=(
                    "AIVA no devolvió el código de vinculación. Intentá iniciar "
                    "la activación nuevamente."
                ),
                endpoint=ENDPOINT_ACTIVATION_PAIRING_CODE,
            )

        return AivaPairingCodeResult(pairing_code=pairing_code, state=state)

    def _parse_activation_status(self, data: dict[str, Any]) -> AivaActivationStatus:
        """Parse the activation status response."""
        state = self._extract_activation_state(data)

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

    async def _get_installation_id(self) -> str:
        """Return a stable Home Assistant installation identifier."""
        installation_id = await async_get_instance_id(self._hass)
        if not installation_id:
            raise AivaInvalidResponseError("Home Assistant no devolvio installation_id")
        return installation_id

    def _extract_activation_state(
        self,
        data: dict[str, Any],
        *,
        default: str | None = None,
    ) -> str:
        """Read activation state from either state or activation_state."""
        state = data.get(FIELD_ACTIVATION_STATE, data.get(FIELD_STATE, default))
        if not isinstance(state, str) or state not in ACTIVATION_STATES:
            raise AivaInvalidResponseError("AIVA devolvio estado invalido")
        return state

    def _resolve_activation_plan(
        self,
        backend_plan: Any,
        *,
        requested_plan: str,
        endpoint: str,
    ) -> str:
        """Resolve the plan during activation, preferring the user-selected one."""
        normalized_requested_plan = requested_plan.strip()
        if not normalized_requested_plan:
            raise AivaInvalidResponseError("AIVA no recibio un plan valido para activar")

        if backend_plan is None:
            _LOGGER.debug(
                "AIVA activation response omitted plan on %s; keeping requested plan=%s",
                endpoint,
                normalized_requested_plan,
            )
            return normalized_requested_plan

        if not isinstance(backend_plan, str):
            raise AivaInvalidResponseError("AIVA devolvio plan invalido")

        normalized_backend_plan = backend_plan.strip()
        if not normalized_backend_plan:
            _LOGGER.warning(
                "AIVA activation response returned empty plan on %s; keeping requested plan=%s",
                endpoint,
                normalized_requested_plan,
            )
            return normalized_requested_plan

        return normalized_backend_plan

    def _parse_home_settings(self, data: dict[str, Any]) -> AivaHomeSettings:
        """Parse home settings from a backend response."""
        settings = data.get(FIELD_SETTINGS, data.get(FIELD_HOME_SETTINGS, data))
        if not isinstance(settings, dict):
            raise AivaInvalidResponseError("AIVA devolvio settings invalidos")

        return AivaHomeSettings(
            language=self._optional_str(settings, "language"),
            assistant_name=self._optional_str(settings, "assistant_name"),
            voice_provider=self._optional_str(settings, "voice_provider"),
            voice_id=self._optional_str(settings, "voice_id"),
            custom_prompt=self._optional_str(settings, "custom_prompt"),
            country_code=self._optional_str(settings, "country_code"),
            locale=self._optional_str(settings, "locale"),
            timezone=self._optional_str(settings, "timezone"),
            response_style=self._optional_str(settings, "response_style"),
        )

    def _parse_effective_entities(
        self,
        data: dict[str, Any],
    ) -> tuple[AivaEffectiveEntity, ...]:
        """Parse effective entity metadata from a backend response."""
        entities = data.get(FIELD_ENTITIES, data.get(FIELD_EFFECTIVE_ENTITIES))
        if not isinstance(entities, list):
            raise AivaInvalidResponseError("AIVA devolvio entidades invalidas")

        parsed: list[AivaEffectiveEntity] = []
        for entity in entities:
            if not isinstance(entity, dict):
                raise AivaInvalidResponseError("AIVA devolvio una entidad invalida")

            entity_id = entity.get("entity_id")
            if not isinstance(entity_id, str) or not entity_id:
                raise AivaInvalidResponseError("AIVA devolvio entity_id invalido")

            parsed.append(
                AivaEffectiveEntity(
                    entity_id=entity_id,
                    display_name=self._optional_str(entity, "display_name"),
                    effective_area=self._optional_str(entity, "effective_area"),
                    alias=self._optional_str(entity, "alias"),
                    area_override=self._optional_str(entity, "area_override"),
                    is_allowed=self._optional_bool(entity, "is_allowed"),
                    is_visible=self._optional_bool(entity, "is_visible"),
                    requires_confirmation=self._optional_bool(
                        entity,
                        "requires_confirmation",
                    ),
                    priority=self._optional_int(entity, "priority"),
                )
            )

        return tuple(parsed)

    def _parse_home_automations(
        self,
        data: dict[str, Any],
    ) -> tuple[AivaHomeAutomation, ...]:
        """Parse home automations from a backend response."""
        automations = data.get(FIELD_AUTOMATIONS, data.get(FIELD_HOME_AUTOMATIONS))
        if not isinstance(automations, list):
            raise AivaInvalidResponseError("AIVA devolvio automatizaciones invalidas")

        parsed: list[AivaHomeAutomation] = []
        for automation in automations:
            if not isinstance(automation, dict):
                raise AivaInvalidResponseError(
                    "AIVA devolvio una automatizacion invalida"
                )

            automation_id = automation.get("id", automation.get("automation_id"))
            if not isinstance(automation_id, str) or not automation_id:
                raise AivaInvalidResponseError("AIVA devolvio automation_id invalido")

            parsed.append(
                AivaHomeAutomation(
                    automation_id=automation_id,
                    name=self._optional_str(automation, "name"),
                    enabled=self._optional_bool(automation, "enabled"),
                    raw=dict(automation),
                )
            )

        return tuple(parsed)

    def _optional_str(self, data: dict[str, Any], field: str) -> str | None:
        """Return an optional string field or reject incompatible values."""
        value = data.get(field)
        if value is None:
            return None
        if not isinstance(value, str):
            raise AivaInvalidResponseError(f"AIVA devolvio {field} invalido")
        return value

    def _optional_bool(self, data: dict[str, Any], field: str) -> bool | None:
        """Return an optional boolean field or reject incompatible values."""
        value = data.get(field)
        if value is None:
            return None
        if not isinstance(value, bool):
            raise AivaInvalidResponseError(f"AIVA devolvio {field} invalido")
        return value

    def _optional_int(self, data: dict[str, Any], field: str) -> int | None:
        """Return an optional integer field or reject incompatible values."""
        value = data.get(field)
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise AivaInvalidResponseError(f"AIVA devolvio {field} invalido")
        return value

    def _ensure_paired(self) -> None:
        """Ensure this client has credentials for paired-home endpoints."""
        if not self._home_id or not self._secret:
            raise AivaInvalidAuthError("AIVA no esta vinculado")

    def _extract_backend_message(self, data: dict[str, Any]) -> str | None:
        """Extract the most useful backend-facing message from a JSON payload."""
        for key in ("detail", "message", "error_description", "title"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        error = data.get("error")
        if isinstance(error, str) and error.strip():
            return error.strip()
        if isinstance(error, dict):
            for key in ("detail", "message", "description", "code"):
                value = error.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()

        return None

    def _sanitize_for_log(self, value: Any) -> Any:
        """Mask sensitive values before writing diagnostics."""
        if isinstance(value, dict):
            return {
                key: self._mask_sensitive_value(key, item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self._sanitize_for_log(item) for item in value]
        return value

    def _mask_sensitive_value(self, key: str, value: Any) -> Any:
        """Mask individual sensitive fields while preserving structure."""
        lowered = key.lower()
        if isinstance(value, dict):
            return self._sanitize_for_log(value)
        if isinstance(value, list):
            return [self._sanitize_for_log(item) for item in value]
        if not isinstance(value, str):
            return value
        if "secret" in lowered:
            return self._mask_token(value, keep_start=2, keep_end=2)
        if "pairing_code" in lowered or "linking_code" in lowered:
            return self._mask_token(value, keep_start=2, keep_end=2)
        return value

    def _sanitize_text_for_log(self, text: str) -> str:
        """Mask sensitive token-like values inside raw backend bodies."""
        if not text:
            return "<empty>"

        sanitized = text
        for field in (FIELD_SECRET, FIELD_PAIRING_CODE):
            marker = f'"{field}"'
            index = sanitized.find(marker)
            while index != -1:
                value_start = sanitized.find('"', index + len(marker))
                value_start = sanitized.find('"', value_start + 1)
                value_end = sanitized.find('"', value_start + 1)
                if value_start == -1 or value_end == -1:
                    break
                raw_value = sanitized[value_start + 1 : value_end]
                sanitized = sanitized.replace(raw_value, self._mask_token(raw_value), 1)
                index = sanitized.find(marker, value_end)

        return sanitized

    def _mask_token(
        self,
        value: str,
        *,
        keep_start: int = 2,
        keep_end: int = 2,
    ) -> str:
        """Mask a token-like string while keeping it identifiable in logs."""
        if len(value) <= keep_start + keep_end:
            return "***"
        return f"{value[:keep_start]}***{value[-keep_end:]}"
