"""Tests for the AIVA config flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.aiva.api import (
    AivaActivationStartResult,
    AivaActivationStatus,
    AivaBackendClientError,
    AivaCannotConnectError,
    AivaInvalidResponseError,
    AivaMissingRequiredDataError,
    AivaTimeoutError,
)
from custom_components.aiva.config_flow import CONF_PAIRING_CONFIRMED
from custom_components.aiva.const import (
    CONF_BASE_URL,
    CONF_HOME_ID,
    CONF_HOME_NAME,
    CONF_PAIRING_CODE,
    CONF_PLAN,
    CONF_SCAN_INTERVAL,
    CONF_SECRET,
    DEFAULT_SCAN_INTERVAL_SECONDS,
    DOMAIN,
    STATE_ACTIVE,
    STATE_AWAITING_PAIRING,
    STATE_AWAITING_PAYMENT,
)


async def test_config_flow_activation_valid_creates_entry(hass):
    """Create a config entry after commercial activation is active."""
    with patch(
        "custom_components.aiva.config_flow._start_activation",
        return_value=AivaActivationStartResult(
            pairing_code="<pairing-code>",
            home_name="Casa Principal",
            plan="smart",
            state=STATE_AWAITING_PAIRING,
            home_id="home-1",
            secret="<redacted-secret>",
        ),
    ), patch(
        "custom_components.aiva.config_flow._get_activation_status",
        side_effect=[
            AivaActivationStatus(state=STATE_AWAITING_PAYMENT),
            AivaActivationStatus(
                state=STATE_ACTIVE,
                home_id="home-1",
                secret="<redacted-secret>",
                home_name="Casa Principal",
                plan="smart",
            ),
        ],
    ) as get_status, patch(
        "custom_components.aiva.async_setup_entry",
        AsyncMock(return_value=True),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={
                CONF_BASE_URL: "https://api.example.com/",
                CONF_HOME_NAME: "Casa Principal",
                CONF_PLAN: "smart",
            },
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "awaiting_pairing"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_PAIRING_CONFIRMED: True},
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "awaiting_payment"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={},
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Casa Principal"
    assert get_status.call_args_list[0].kwargs == {
        "base_url": "https://api.example.com",
        "home_id": "home-1",
        "secret": "<redacted-secret>",
        "home_name": "Casa Principal",
    }
    assert result["data"] == {
        CONF_BASE_URL: "https://api.example.com",
        CONF_HOME_ID: "home-1",
        CONF_SECRET: "<redacted-secret>",
        CONF_HOME_NAME: "Casa Principal",
        CONF_PLAN: "smart",
    }


async def test_config_flow_pairing_step_exposes_direct_bot_link_when_configured(hass):
    """Show a direct Telegram deep link when the bot username is configured."""
    with patch(
        "custom_components.aiva.config_flow.TELEGRAM_BOT_USERNAME",
        "aiva_asistente_1_bot",
    ), patch(
        "custom_components.aiva.config_flow._start_activation",
        return_value=AivaActivationStartResult(
            pairing_code="<pairing-code>",
            home_name="Casa Principal",
            plan="base",
            state=STATE_AWAITING_PAIRING,
            home_id="home-1",
            secret="<redacted-secret>",
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={
                CONF_BASE_URL: "https://api.example.com",
                CONF_PLAN: "base",
                CONF_HOME_NAME: "Casa Principal",
            },
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "awaiting_pairing"
    assert (
        result["description_placeholders"]["telegram_bot_url"]
        == "https://t.me/aiva_asistente_1_bot?start=%3Cpairing-code%3E"
    )
    assert (
        result["description_placeholders"]["telegram_bot_link_md"]
        == "[Abrir bot de AIVA](https://t.me/aiva_asistente_1_bot?start=%3Cpairing-code%3E)"
    )
    assert (
        result["description_placeholders"]["telegram_bot_username"]
        == "@aiva_asistente_1_bot"
    )


async def test_config_flow_pairing_step_falls_back_to_manual_telegram_instructions(hass):
    """Keep a simple manual UX if the Telegram bot username is not configured."""
    with patch(
        "custom_components.aiva.config_flow.TELEGRAM_BOT_USERNAME",
        "",
    ), patch(
        "custom_components.aiva.config_flow._start_activation",
        return_value=AivaActivationStartResult(
            pairing_code="<pairing-code>",
            home_name="Casa Principal",
            plan="base",
            state=STATE_AWAITING_PAIRING,
            home_id="home-1",
            secret="<redacted-secret>",
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={
                CONF_BASE_URL: "https://api.example.com",
                CONF_PLAN: "base",
                CONF_HOME_NAME: "Casa Principal",
            },
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "awaiting_pairing"
    assert result["description_placeholders"]["telegram_bot_url"] == ""
    assert result["description_placeholders"]["telegram_bot_link_md"] == ""
    assert "buscá el bot de AIVA" in result["description_placeholders"]["telegram_bot_help"]


async def test_config_flow_pairing_pending(hass):
    """Show a clear form error while external pairing is pending."""
    with patch(
        "custom_components.aiva.config_flow._start_activation",
        return_value=AivaActivationStartResult(
            pairing_code="<pairing-code>",
            home_name="Casa Principal",
            plan="base",
            state=STATE_AWAITING_PAIRING,
            home_id="home-1",
            secret="<redacted-secret>",
        ),
    ), patch(
        "custom_components.aiva.config_flow._get_activation_status",
        return_value=AivaActivationStatus(state=STATE_AWAITING_PAIRING),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={
                CONF_BASE_URL: "https://api.example.com",
                CONF_PLAN: "base",
                CONF_HOME_NAME: "Casa Principal",
            },
        )

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_PAIRING_CONFIRMED: True},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "awaiting_pairing"
    assert result["errors"] == {"base": "pairing_pending"}


async def test_config_flow_keeps_user_plan_when_status_omits_it(hass):
    """Persist the selected plan if later activation steps do not return it."""
    with patch(
        "custom_components.aiva.config_flow._start_activation",
        return_value=AivaActivationStartResult(
            pairing_code="<pairing-code>",
            home_name="Casa Principal",
            plan="premium",
            state=STATE_AWAITING_PAIRING,
            home_id="home-1",
            secret="<redacted-secret>",
        ),
    ), patch(
        "custom_components.aiva.config_flow._get_activation_status",
        side_effect=[
            AivaActivationStatus(state=STATE_AWAITING_PAYMENT),
            AivaActivationStatus(
                state=STATE_ACTIVE,
                home_id="home-1",
                secret="<redacted-secret>",
                home_name="Casa Principal",
                plan=None,
            ),
        ],
    ), patch(
        "custom_components.aiva.async_setup_entry",
        AsyncMock(return_value=True),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={
                CONF_BASE_URL: "https://api.example.com/",
                CONF_HOME_NAME: "Casa Principal",
                CONF_PLAN: "premium",
            },
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "awaiting_pairing"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_PAIRING_CONFIRMED: True},
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "awaiting_payment"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={},
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_PLAN] == "premium"


async def test_config_flow_timeout_or_unreachable(hass):
    """Show cannot_connect when the backend cannot be reached."""
    with patch(
        "custom_components.aiva.config_flow._start_activation",
        side_effect=AivaCannotConnectError("backend unreachable"),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={
                CONF_BASE_URL: "https://api.example.com",
                CONF_PLAN: "base",
                CONF_HOME_NAME: "Casa Principal",
            },
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_config_flow_invalid_backend_response(hass):
    """Show invalid_response for malformed backend responses."""
    with patch(
        "custom_components.aiva.config_flow._start_activation",
        side_effect=AivaInvalidResponseError("invalid backend payload"),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={
                CONF_BASE_URL: "https://api.example.com",
                CONF_PLAN: "base",
                CONF_HOME_NAME: "Casa Principal",
            },
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_response"}


async def test_config_flow_incomplete_backend_response(hass):
    """Show missing_required_data when pairing lacks home_id or secret."""
    with patch(
        "custom_components.aiva.config_flow._start_activation",
        side_effect=AivaMissingRequiredDataError("missing required activation data"),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={
                CONF_BASE_URL: "https://api.example.com",
                CONF_PLAN: "base",
                CONF_HOME_NAME: "Casa Principal",
            },
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "missing_required_data"}


async def test_config_flow_does_not_duplicate_existing_entry(hass):
    """Abort when AIVA is already configured."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Casa Principal",
        data={
            CONF_BASE_URL: "http://127.0.0.1:8080",
            CONF_HOME_ID: "home-1",
            CONF_SECRET: "<redacted-secret>",
            CONF_HOME_NAME: "Casa Principal",
        },
        source=config_entries.SOURCE_USER,
        entry_id="test-entry",
        unique_id="home-1",
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_options_flow_updates_base_url_and_scan_interval(hass):
    """Allow changing backend URL and update interval without reinstalling."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Casa Principal",
        data={
            CONF_BASE_URL: "http://127.0.0.1:8080",
            CONF_PAIRING_CODE: "<pairing-code>",
            CONF_HOME_ID: "home-1",
            CONF_SECRET: "<redacted-secret>",
            CONF_HOME_NAME: "Casa Principal",
        },
        source=config_entries.SOURCE_USER,
        entry_id="test-entry",
        unique_id="home-1",
        options={},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_BASE_URL: "https://api.example.com/",
            CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL_SECONDS,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        CONF_BASE_URL: "https://api.example.com",
        CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL_SECONDS,
    }


async def test_config_flow_rejects_localhost_base_url(hass):
    """Reject localhost URLs during initial activation."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
        data={
            CONF_BASE_URL: " http://127.0.0.1:8080/ ",
            CONF_PLAN: "base",
            CONF_HOME_NAME: "Casa Principal",
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_BASE_URL: "invalid_base_url_local"}


async def test_config_flow_rejects_blank_home_name(hass):
    """Reject empty or whitespace-only home names."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
        data={
            CONF_BASE_URL: "https://api.example.com",
            CONF_PLAN: "base",
            CONF_HOME_NAME: "   ",
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_HOME_NAME: "invalid_home_name"}


async def test_config_flow_shows_backend_client_error_detail(hass):
    """Surface useful backend details in the form description."""
    with patch(
        "custom_components.aiva.config_flow._start_activation",
        side_effect=AivaBackendClientError(
            "HTTP 422",
            user_message="El plan seleccionado no está disponible",
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={
                CONF_BASE_URL: "https://api.example.com",
                CONF_PLAN: "base",
                CONF_HOME_NAME: "Casa Principal",
            },
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "backend_client_error"}
    assert (
        result["description_placeholders"]["error_detail"]
        == "Detalle del error: El plan seleccionado no está disponible"
    )


async def test_config_flow_maps_timeout_separately(hass):
    """Differentiate backend timeouts from generic connection failures."""
    with patch(
        "custom_components.aiva.config_flow._start_activation",
        side_effect=AivaTimeoutError("timeout"),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={
                CONF_BASE_URL: "https://api.example.com",
                CONF_PLAN: "base",
                CONF_HOME_NAME: "Casa Principal",
            },
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "timeout"}


async def test_config_flow_pairing_requires_explicit_confirmation(hass):
    """Keep awaiting_pairing guided until the user confirms the external step."""
    with patch(
        "custom_components.aiva.config_flow._start_activation",
        return_value=AivaActivationStartResult(
            pairing_code="<pairing-code>",
            home_name="Casa Principal",
            plan="base",
            state=STATE_AWAITING_PAIRING,
            home_id="home-1",
            secret="<redacted-secret>",
        ),
    ), patch(
        "custom_components.aiva.config_flow._get_activation_status",
    ) as get_status:
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={
                CONF_BASE_URL: "https://api.example.com",
                CONF_PLAN: "base",
                CONF_HOME_NAME: "Casa Principal",
            },
        )

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_PAIRING_CONFIRMED: False},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "awaiting_pairing"
    assert result["errors"] == {CONF_PAIRING_CONFIRMED: "confirm_pairing_required"}
    get_status.assert_not_called()


async def test_config_flow_pairing_404_is_treated_as_pending(hass):
    """Treat backend 404 during pairing poll as a pending external link."""
    with patch(
        "custom_components.aiva.config_flow._start_activation",
        return_value=AivaActivationStartResult(
            pairing_code="<pairing-code>",
            home_name="Casa Principal",
            plan="base",
            state=STATE_AWAITING_PAIRING,
            home_id="home-1",
            secret="<redacted-secret>",
        ),
    ), patch(
        "custom_components.aiva.config_flow._get_activation_status",
        side_effect=AivaBackendClientError(
            "HTTP 404",
            user_message="Not Found",
            status=404,
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={
                CONF_BASE_URL: "https://api.example.com",
                CONF_PLAN: "base",
                CONF_HOME_NAME: "Casa Principal",
            },
        )

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_PAIRING_CONFIRMED: True},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "awaiting_pairing"
    assert result["errors"] == {"base": "pairing_pending"}
    assert result["description_placeholders"]["error_detail"] == ""
