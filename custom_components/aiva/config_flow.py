"""Config flow for the AIVA integration."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote, urlparse

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant

from .api import (
    AivaActivationStartResult,
    AivaActivationStatus,
    AivaApiClient,
    AivaApiError,
    AivaBackendClientError,
    AivaBackendServerError,
    AivaCannotConnectError,
    AivaConnectionError,
    AivaInvalidPairingCodeError,
    AivaInvalidResponseError,
    AivaMissingRequiredDataError,
    AivaTimeoutError,
)
from .const import (
    CONF_BASE_URL,
    CONF_HOME_ID,
    CONF_HOME_NAME,
    CONF_PLAN,
    CONF_SCAN_INTERVAL,
    CONF_SECRET,
    DEFAULT_API_BASE_URL,
    DEFAULT_SCAN_INTERVAL_SECONDS,
    DOMAIN,
    MIN_SCAN_INTERVAL_SECONDS,
    PLANS,
    STATE_ACTIVE,
    STATE_AWAITING_PAIRING,
    STATE_AWAITING_PAYMENT,
    STATE_SUSPENDED,
    TELEGRAM_BOT_USERNAME,
)

_LOGGER = logging.getLogger(__name__)
CONF_PAIRING_CONFIRMED = "pairing_confirmed"


STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_BASE_URL, default=DEFAULT_API_BASE_URL): str,
        vol.Required(CONF_HOME_NAME): str,
        vol.Required(CONF_PLAN, default="base"): vol.In(PLANS),
    }
)

EMPTY_SCHEMA = vol.Schema({})
STEP_AWAITING_PAIRING_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PAIRING_CONFIRMED, default=False): bool,
    }
)


def _normalize_user_base_url(base_url: Any) -> str:
    """Normalize user-provided base URL values."""
    value = AivaApiClient.normalize_base_url(str(base_url or ""))
    parsed = urlparse(value)
    if not value or parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return value


def _is_blocked_base_url(base_url: str) -> bool:
    """Reject local-only URLs in the activation flow."""
    parsed = urlparse(base_url)
    return parsed.hostname in {"localhost", "127.0.0.1", "::1"}


def _format_user_error_detail(message: str | None) -> str:
    """Render a concrete backend detail without leaking secrets."""
    if not message:
        return ""
    return f"Detalle del error: {message}"


def _build_telegram_pairing_placeholders(pairing_code: str | None) -> dict[str, str]:
    """Build user-facing placeholders for the pairing onboarding step."""
    code = (pairing_code or "").strip()
    bot_username = TELEGRAM_BOT_USERNAME.strip().lstrip("@")

    if not bot_username:
        return {
            "pairing_code": code,
            "telegram_bot_username": "",
            "telegram_bot_url": "",
            "telegram_bot_link_md": "",
            "telegram_bot_help": (
                "Abrí Telegram en tu celular o computadora, buscá el bot de AIVA "
                "que te compartieron y enviale el código exacto."
            ),
        }

    telegram_bot_url = f"https://t.me/{bot_username}"
    deep_link = f"{telegram_bot_url}?start={quote(code)}" if code else telegram_bot_url

    return {
        "pairing_code": code,
        "telegram_bot_username": f"@{bot_username}",
        "telegram_bot_url": deep_link,
        "telegram_bot_link_md": f"[Abrir bot de AIVA]({deep_link})",
        "telegram_bot_help": (
            f"Si preferís abrirlo manualmente, buscá `@{bot_username}` en Telegram."
        ),
    }


async def _start_activation(
    hass: HomeAssistant,
    user_input: dict[str, Any],
) -> AivaActivationStartResult:
    """Start the commercial activation flow."""
    client = AivaApiClient(
        hass=hass,
        base_url=user_input[CONF_BASE_URL],
    )
    return await client.start_activation(
        home_name=user_input[CONF_HOME_NAME],
        plan=user_input[CONF_PLAN],
    )


async def _get_activation_status(
    hass: HomeAssistant,
    *,
    base_url: str,
    home_id: str,
    secret: str,
    home_name: str | None = None,
) -> AivaActivationStatus:
    """Fetch the commercial activation state."""
    client = AivaApiClient(
        hass=hass,
        base_url=base_url,
        home_id=home_id,
        secret=secret,
        home_name=home_name,
    )
    return await client.get_activation_status()


class AivaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle an AIVA config flow."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the AIVA config flow."""
        self._base_url: str | None = None
        self._home_name: str | None = None
        self._home_id: str | None = None
        self._plan: str | None = None
        self._pairing_code: str | None = None
        self._secret: str | None = None
        self._last_error_detail: str = ""

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the AIVA options flow."""
        return AivaOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if self._async_current_entries():
            return self.async_abort(reason="already_configured")

        if user_input is not None:
            base_url = _normalize_user_base_url(user_input.get(CONF_BASE_URL))
            home_name = (user_input.get(CONF_HOME_NAME) or "").strip()
            plan = user_input[CONF_PLAN]

            if not base_url:
                errors[CONF_BASE_URL] = "invalid_base_url"
            elif _is_blocked_base_url(base_url):
                errors[CONF_BASE_URL] = "invalid_base_url_local"

            if not home_name:
                errors[CONF_HOME_NAME] = "invalid_home_name"

            normalized_input: dict[str, Any] | None = None
            if not errors:
                normalized_input = {
                    CONF_BASE_URL: base_url,
                    CONF_HOME_NAME: home_name,
                    CONF_PLAN: plan,
                }
                _LOGGER.debug(
                    "AIVA activation requested from config flow: base_url=%s plan=%s home_name=%s",
                    base_url,
                    plan,
                    home_name,
                )

            if normalized_input is not None:
                try:
                    activation = await _start_activation(self.hass, normalized_input)
                except AivaApiError as err:
                    self._apply_api_error(errors, err)
                else:
                    self._last_error_detail = ""
                    self._base_url = base_url
                    self._home_name = activation.home_name
                    self._home_id = activation.home_id
                    self._plan = activation.plan
                    self._pairing_code = activation.pairing_code
                    self._secret = activation.secret

                    if activation.state == STATE_ACTIVE:
                        return await self._create_active_entry(
                            AivaActivationStatus(
                                state=activation.state,
                                home_id=activation.home_id,
                                secret=activation.secret,
                                home_name=activation.home_name,
                                plan=activation.plan,
                            )
                        )
                    if activation.state in {STATE_AWAITING_PAYMENT, STATE_SUSPENDED}:
                        return await self.async_step_awaiting_payment()
                    return await self.async_step_awaiting_pairing()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
            description_placeholders={"error_detail": self._last_error_detail},
        )

    async def async_step_awaiting_pairing(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Wait until the backend reports that external pairing is complete."""
        errors: dict[str, str] = {}

        if user_input is not None:
            if not user_input.get(CONF_PAIRING_CONFIRMED):
                errors[CONF_PAIRING_CONFIRMED] = "confirm_pairing_required"
            else:
                status = await self._poll_activation_status(
                    errors,
                    treat_not_found_as_pending=True,
                )
                if status:
                    self._last_error_detail = ""
                    if status.state == STATE_ACTIVE:
                        return await self._create_active_entry(status)
                    if status.state == STATE_AWAITING_PAYMENT:
                        return await self.async_step_awaiting_payment()

                    errors["base"] = "pairing_pending"

        return self.async_show_form(
            step_id="awaiting_pairing",
            data_schema=STEP_AWAITING_PAIRING_DATA_SCHEMA,
            errors=errors,
            description_placeholders={
                **_build_telegram_pairing_placeholders(self._pairing_code),
                "error_detail": self._last_error_detail,
            },
        )

    async def async_step_awaiting_payment(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Wait until the backend marks the home as commercially active."""
        errors: dict[str, str] = {}

        if user_input is not None:
            status = await self._poll_activation_status(errors)
            if status:
                self._last_error_detail = ""
                if status.state == STATE_ACTIVE:
                    return await self._create_active_entry(status)
                if status.state == STATE_AWAITING_PAIRING:
                    return await self.async_step_awaiting_pairing()

                errors["base"] = "payment_pending"

        return self.async_show_form(
            step_id="awaiting_payment",
            data_schema=EMPTY_SCHEMA,
            errors=errors,
            description_placeholders={"error_detail": self._last_error_detail},
        )

    async def _poll_activation_status(
        self,
        errors: dict[str, str],
        *,
        treat_not_found_as_pending: bool = False,
    ) -> AivaActivationStatus | None:
        """Poll activation status and translate backend errors for the flow."""
        if not self._base_url or not self._home_id or not self._secret:
            errors["base"] = "missing_required_data"
            return None

        try:
            return await _get_activation_status(
                self.hass,
                base_url=self._base_url,
                home_id=self._home_id,
                secret=self._secret,
                home_name=self._home_name,
            )
        except AivaApiError as err:
            if (
                treat_not_found_as_pending
                and isinstance(err, AivaBackendClientError)
                and err.status == 404
            ):
                self._last_error_detail = ""
                errors["base"] = "pairing_pending"
                return None
            self._apply_api_error(errors, err)

        return None

    async def _create_active_entry(
        self,
        status: AivaActivationStatus,
    ) -> config_entries.ConfigFlowResult:
        """Create the final active config entry."""
        if not status.home_id or not status.secret:
            return self.async_show_form(
                step_id="awaiting_payment",
                data_schema=EMPTY_SCHEMA,
                errors={"base": "missing_required_data"},
            )

        await self.async_set_unique_id(status.home_id)
        self._abort_if_unique_id_configured()

        home_name = status.home_name or self._home_name or "Casa AIVA"
        entry_data = {
            CONF_BASE_URL: self._base_url or DEFAULT_API_BASE_URL,
            CONF_HOME_ID: status.home_id,
            CONF_SECRET: status.secret,
            CONF_HOME_NAME: home_name,
            CONF_PLAN: status.plan or self._plan or "base",
        }

        return self.async_create_entry(
            title=home_name,
            data=entry_data,
        )

    def _apply_api_error(self, errors: dict[str, str], err: AivaApiError) -> None:
        """Map API exceptions to Home Assistant flow errors and visible details."""
        self._last_error_detail = _format_user_error_detail(err.user_message)

        if isinstance(err, AivaInvalidPairingCodeError):
            errors["base"] = "invalid_pairing_code"
        elif isinstance(err, AivaTimeoutError):
            errors["base"] = "timeout"
        elif isinstance(err, AivaConnectionError):
            errors["base"] = "cannot_connect"
        elif isinstance(err, AivaBackendClientError):
            errors["base"] = "backend_client_error"
        elif isinstance(err, AivaBackendServerError):
            errors["base"] = "backend_server_error"
        elif isinstance(err, AivaMissingRequiredDataError):
            errors["base"] = "missing_required_data"
        elif isinstance(err, AivaInvalidResponseError):
            errors["base"] = "invalid_response"
        elif isinstance(err, AivaCannotConnectError):
            errors["base"] = "cannot_connect"
        else:
            errors["base"] = "unknown"


class AivaOptionsFlow(config_entries.OptionsFlow):
    """Handle AIVA options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize the options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Manage AIVA options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            base_url = _normalize_user_base_url(user_input[CONF_BASE_URL])
            scan_interval = user_input[CONF_SCAN_INTERVAL]

            if not base_url:
                errors[CONF_BASE_URL] = "invalid_base_url"
            elif _is_blocked_base_url(base_url):
                errors[CONF_BASE_URL] = "invalid_base_url_local"
            elif scan_interval < MIN_SCAN_INTERVAL_SECONDS:
                errors[CONF_SCAN_INTERVAL] = "invalid_scan_interval"
            else:
                return self.async_create_entry(
                    title="",
                    data={
                        CONF_BASE_URL: base_url,
                        CONF_SCAN_INTERVAL: scan_interval,
                    },
                )

        current_base_url = self._config_entry.options.get(
            CONF_BASE_URL,
            self._config_entry.data.get(CONF_BASE_URL, DEFAULT_API_BASE_URL),
        )
        current_scan_interval = self._config_entry.options.get(
            CONF_SCAN_INTERVAL,
            DEFAULT_SCAN_INTERVAL_SECONDS,
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_BASE_URL, default=current_base_url): str,
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=current_scan_interval,
                    ): vol.Coerce(int),
                }
            ),
            errors=errors,
        )
