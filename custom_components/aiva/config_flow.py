"""Config flow for the AIVA integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant

from .api import (
    AivaActivationStartResult,
    AivaActivationStatus,
    AivaApiClient,
    AivaApiError,
    AivaCannotConnectError,
    AivaInvalidPairingCodeError,
    AivaInvalidResponseError,
    AivaMissingRequiredDataError,
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
)


STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_BASE_URL, default=DEFAULT_API_BASE_URL): str,
        vol.Optional(CONF_HOME_NAME): str,
        vol.Required(CONF_PLAN, default="base"): vol.In(PLANS),
    }
)

EMPTY_SCHEMA = vol.Schema({})


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
    pairing_code: str,
) -> AivaActivationStatus:
    """Fetch the commercial activation state."""
    client = AivaApiClient(
        hass=hass,
        base_url=base_url,
        pairing_code=pairing_code,
    )
    return await client.get_activation_status(pairing_code=pairing_code)


class AivaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle an AIVA config flow."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the AIVA config flow."""
        self._base_url: str | None = None
        self._home_name: str | None = None
        self._plan: str | None = None
        self._pairing_code: str | None = None

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
            base_url = user_input[CONF_BASE_URL].strip().rstrip("/")
            home_name = user_input.get(CONF_HOME_NAME, "").strip()
            requested_home_name = (
                home_name or self.hass.config.location_name or "Casa AIVA"
            )
            plan = user_input[CONF_PLAN]

            normalized_input: dict[str, Any] = {
                CONF_BASE_URL: base_url,
                CONF_HOME_NAME: requested_home_name,
                CONF_PLAN: plan,
            }

            try:
                activation = await _start_activation(self.hass, normalized_input)
            except AivaCannotConnectError:
                errors["base"] = "cannot_connect"
            except AivaMissingRequiredDataError:
                errors["base"] = "missing_required_data"
            except AivaInvalidResponseError:
                errors["base"] = "invalid_response"
            except AivaApiError:
                errors["base"] = "unknown"
            else:
                self._base_url = base_url
                self._home_name = activation.home_name
                self._plan = activation.plan
                self._pairing_code = activation.pairing_code

                if activation.state == STATE_ACTIVE:
                    return await self.async_step_awaiting_payment()
                if activation.state == STATE_AWAITING_PAYMENT:
                    return await self.async_step_awaiting_payment()
                return await self.async_step_awaiting_pairing()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_awaiting_pairing(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Wait until the backend reports that external pairing is complete."""
        errors: dict[str, str] = {}

        if user_input is not None:
            status = await self._poll_activation_status(errors)
            if status:
                if status.state == STATE_ACTIVE:
                    return await self._create_active_entry(status)
                if status.state == STATE_AWAITING_PAYMENT:
                    return await self.async_step_awaiting_payment()

                errors["base"] = "pairing_pending"

        return self.async_show_form(
            step_id="awaiting_pairing",
            data_schema=EMPTY_SCHEMA,
            errors=errors,
            description_placeholders={
                "pairing_code": self._pairing_code or "",
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
                if status.state == STATE_ACTIVE:
                    return await self._create_active_entry(status)
                if status.state == STATE_AWAITING_PAIRING:
                    return await self.async_step_awaiting_pairing()

                errors["base"] = "payment_pending"

        return self.async_show_form(
            step_id="awaiting_payment",
            data_schema=EMPTY_SCHEMA,
            errors=errors,
        )

    async def _poll_activation_status(
        self,
        errors: dict[str, str],
    ) -> AivaActivationStatus | None:
        """Poll activation status and translate backend errors for the flow."""
        if not self._base_url or not self._pairing_code:
            errors["base"] = "missing_required_data"
            return None

        try:
            return await _get_activation_status(
                self.hass,
                base_url=self._base_url,
                pairing_code=self._pairing_code,
            )
        except AivaInvalidPairingCodeError:
            errors["base"] = "invalid_pairing_code"
        except AivaCannotConnectError:
            errors["base"] = "cannot_connect"
        except AivaMissingRequiredDataError:
            errors["base"] = "missing_required_data"
        except AivaInvalidResponseError:
            errors["base"] = "invalid_response"
        except AivaApiError:
            errors["base"] = "unknown"

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
            base_url = user_input[CONF_BASE_URL].strip().rstrip("/")
            scan_interval = user_input[CONF_SCAN_INTERVAL]

            if scan_interval < MIN_SCAN_INTERVAL_SECONDS:
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
