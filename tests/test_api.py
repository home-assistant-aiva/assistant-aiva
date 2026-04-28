"""Tests for the AIVA API client."""

from __future__ import annotations

import logging

from aiohttp import ClientError
import json
import pytest

from custom_components.aiva.api import (
    AivaApiClient,
    AivaBackendClientError,
    AivaCannotConnectError,
    AivaConnectionError,
    AivaInvalidPairingCodeError,
    AivaInvalidResponseError,
    AivaMissingRequiredDataError,
    AivaTimeoutError,
)
from custom_components.aiva.const import (
    STATE_ACTIVE,
    STATE_AWAITING_PAIRING,
    STATE_AWAITING_PAYMENT,
    STATE_SUSPENDED,
)


class FakeResponse:
    """Minimal aiohttp response test double."""

    def __init__(self, status: int, payload, *, headers=None):
        """Initialize the response."""
        self.status = status
        self._payload = payload
        self.headers = headers or {}

    async def __aenter__(self):
        """Enter response context."""
        return self

    async def __aexit__(self, exc_type, exc, tb):
        """Exit response context."""
        return False

    async def json(self, content_type=None):
        """Return the configured JSON payload."""
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload

    async def text(self):
        """Return the configured body as text."""
        if isinstance(self._payload, Exception):
            raise self._payload
        if isinstance(self._payload, str):
            return self._payload
        return json.dumps(self._payload)


class FakeSession:
    """Minimal aiohttp session test double."""

    def __init__(self, response_or_error):
        """Initialize the session."""
        self.response_or_error = response_or_error
        self.calls = []

    def request(self, method, url, **kwargs):
        """Record and return the configured response."""
        self.calls.append({"method": method, "url": url, **kwargs})
        if isinstance(self.response_or_error, Exception):
            raise self.response_or_error
        return self.response_or_error


def _patch_session(monkeypatch, response_or_error):
    session = FakeSession(response_or_error)
    monkeypatch.setattr(
        "custom_components.aiva.api.async_get_clientsession",
        lambda hass: session,
    )
    return session


def _patch_installation_id(monkeypatch, installation_id="ha-installation-1"):
    async def _async_get_instance_id(hass):
        return installation_id

    monkeypatch.setattr(
        "custom_components.aiva.api.async_get_instance_id",
        _async_get_instance_id,
    )


@pytest.mark.asyncio
async def test_validate_pairing_code_success(hass, monkeypatch):
    """Validate a pairing code and parse the backend response."""
    session = _patch_session(
        monkeypatch,
        FakeResponse(
            200,
            {
                "ok": True,
                "home_id": "home-1",
                "home_name": "Casa Principal",
                "secret": "<redacted-secret>",
                "plan": "smart",
            },
        ),
    )
    client = AivaApiClient(hass, base_url="https://api.example.com")

    result = await client.validate_pairing_code("<pairing-code>", "Casa Principal")

    assert result.home_id == "home-1"
    assert result.secret == "<redacted-secret>"
    assert session.calls[0]["url"] == "https://api.example.com/pair"
    assert session.calls[0]["json"] == {
        "pairing_code": "<pairing-code>",
        "home_name": "Casa Principal",
    }


@pytest.mark.asyncio
async def test_validate_pairing_code_invalid(hass, monkeypatch):
    """Raise a clear error for invalid, expired, or used pairing codes."""
    _patch_session(
        monkeypatch,
        FakeResponse(400, {"error": {"code": "invalid_pairing_code"}}),
    )
    client = AivaApiClient(hass, base_url="http://127.0.0.1:8080")

    with pytest.raises(AivaInvalidPairingCodeError):
        await client.validate_pairing_code("<invalid-pairing-code>", "Casa")


@pytest.mark.asyncio
async def test_validate_pairing_code_timeout(hass, monkeypatch):
    """Translate backend timeouts into connection errors."""
    _patch_session(monkeypatch, TimeoutError())
    client = AivaApiClient(hass, base_url="http://127.0.0.1:8080")

    with pytest.raises(AivaTimeoutError):
        await client.validate_pairing_code("<pairing-code>", "Casa")


@pytest.mark.asyncio
async def test_validate_pairing_code_backend_unreachable(hass, monkeypatch):
    """Translate network failures into connection errors."""
    _patch_session(monkeypatch, ClientError("unreachable"))
    client = AivaApiClient(hass, base_url="http://127.0.0.1:8080")

    with pytest.raises(AivaConnectionError):
        await client.validate_pairing_code("<pairing-code>", "Casa")


@pytest.mark.asyncio
async def test_validate_pairing_code_invalid_response(hass, monkeypatch):
    """Reject non-object or malformed backend responses."""
    _patch_session(monkeypatch, FakeResponse(200, ["not", "a", "dict"]))
    client = AivaApiClient(hass, base_url="http://127.0.0.1:8080")

    with pytest.raises(AivaInvalidResponseError):
        await client.validate_pairing_code("<pairing-code>", "Casa")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"ok": True, "secret": "<redacted-secret>", "home_name": "Casa"},
        {"ok": True, "home_id": "home-1", "home_name": "Casa"},
    ],
)
async def test_validate_pairing_code_incomplete_response(hass, monkeypatch, payload):
    """Reject successful pairing responses without required credentials."""
    _patch_session(monkeypatch, FakeResponse(200, payload))
    client = AivaApiClient(hass, base_url="http://127.0.0.1:8080")

    with pytest.raises(AivaMissingRequiredDataError):
        await client.validate_pairing_code("<pairing-code>", "Casa")


@pytest.mark.asyncio
async def test_start_activation_success(hass, monkeypatch):
    """Start activation using the two-step backend flow."""
    responses = [
        FakeResponse(
            200,
            {
                "ok": True,
                "home_id": "home-1",
                "secret": "<redacted-secret>",
                "home_name": "Casa Principal",
                "plan": "premium",
                "activation_state": " Installed ",
            },
        ),
        FakeResponse(
            200,
            {
                "ok": True,
                "pairing_code": "<pairing-code>",
                "activation_state": STATE_AWAITING_PAIRING,
            },
        ),
    ]

    class SequencedSession(FakeSession):
        def request(self, method, url, **kwargs):
            self.calls.append({"method": method, "url": url, **kwargs})
            return responses.pop(0)

    _patch_installation_id(monkeypatch)
    session = SequencedSession(None)
    monkeypatch.setattr(
        "custom_components.aiva.api.async_get_clientsession",
        lambda hass: session,
    )
    client = AivaApiClient(hass, base_url="https://api.example.com")

    result = await client.start_activation(
        home_name="Casa Principal",
        plan="premium",
    )

    assert result.pairing_code == "<pairing-code>"
    assert result.state == STATE_AWAITING_PAIRING
    assert result.home_id == "home-1"
    assert result.secret == "<redacted-secret>"
    assert session.calls[0]["url"] == "https://api.example.com/activation/request"
    assert session.calls[0]["json"] == {
        "installation_id": "ha-installation-1",
        "home_name": "Casa Principal",
        "plan": "premium",
    }
    assert session.calls[1]["url"] == "https://api.example.com/activation/pairing-code"
    assert session.calls[1]["json"] == {"home_id": "home-1"}
    assert session.calls[1]["headers"] == {"x-aiva-secret": "<redacted-secret>"}


@pytest.mark.asyncio
async def test_start_activation_uses_requested_plan_when_backend_returns_null(
    hass, monkeypatch
):
    """Keep the user-selected plan when the first step omits it with null."""
    responses = [
        FakeResponse(
            200,
            {
                "ok": True,
                "home_id": "home-1",
                "secret": "<redacted-secret>",
                "home_name": "Casa Principal",
                "plan": None,
                "activation_state": "installed",
            },
        ),
        FakeResponse(
            200,
            {
                "ok": True,
                "pairing_code": "<pairing-code>",
                "activation_state": STATE_AWAITING_PAIRING,
            },
        ),
    ]

    class SequencedSession(FakeSession):
        def request(self, method, url, **kwargs):
            self.calls.append({"method": method, "url": url, **kwargs})
            return responses.pop(0)

    _patch_installation_id(monkeypatch)
    session = SequencedSession(None)
    monkeypatch.setattr(
        "custom_components.aiva.api.async_get_clientsession",
        lambda hass: session,
    )
    client = AivaApiClient(hass, base_url="https://api.example.com")

    result = await client.start_activation(
        home_name="Casa Principal",
        plan="premium",
    )

    assert result.plan == "premium"
    assert result.pairing_code == "<pairing-code>"


@pytest.mark.asyncio
async def test_start_activation_uses_requested_plan_when_backend_omits_plan(
    hass, monkeypatch
):
    """Keep the user-selected plan when the first step omits the field."""
    responses = [
        FakeResponse(
            200,
            {
                "ok": True,
                "home_id": "home-1",
                "secret": "<redacted-secret>",
                "home_name": "Casa Principal",
                "activation_state": "installed",
            },
        ),
        FakeResponse(
            200,
            {
                "ok": True,
                "pairing_code": "<pairing-code>",
                "activation_state": STATE_AWAITING_PAIRING,
            },
        ),
    ]

    class SequencedSession(FakeSession):
        def request(self, method, url, **kwargs):
            self.calls.append({"method": method, "url": url, **kwargs})
            return responses.pop(0)

    _patch_installation_id(monkeypatch)
    session = SequencedSession(None)
    monkeypatch.setattr(
        "custom_components.aiva.api.async_get_clientsession",
        lambda hass: session,
    )
    client = AivaApiClient(hass, base_url="https://api.example.com")

    result = await client.start_activation(
        home_name="Casa Principal",
        plan="smart",
    )

    assert result.plan == "smart"
    assert result.pairing_code == "<pairing-code>"


@pytest.mark.asyncio
async def test_start_activation_accepts_pairing_code_in_first_response(hass, monkeypatch):
    """Keep compatibility when the first endpoint still returns pairing_code."""
    _patch_installation_id(monkeypatch)
    session = _patch_session(
        monkeypatch,
        FakeResponse(
            200,
            {
                "ok": True,
                "pairing_code": "<pairing-code>",
                "home_name": "Casa Principal",
                "plan": "premium",
                "activation_state": STATE_AWAITING_PAIRING,
            },
        ),
    )
    client = AivaApiClient(hass, base_url="https://api.example.com")

    result = await client.start_activation(home_name="Casa Principal", plan="premium")

    assert result.pairing_code == "<pairing-code>"
    assert len(session.calls) == 1


@pytest.mark.asyncio
async def test_start_activation_accepts_nested_activation_request_payload(
    hass, monkeypatch
):
    """Parse activation/request when the backend wraps the activation payload."""
    responses = [
        FakeResponse(
            200,
            {
                "ok": True,
                "state": "success",
                "data": {
                    "home_id": "home-1",
                    "secret": "<redacted-secret>",
                    "home_name": "Casa Principal",
                    "plan": "premium",
                    "activation_state": "installed",
                },
            },
        ),
        FakeResponse(
            200,
            {
                "ok": True,
                "data": {
                    "pairing_code": "<pairing-code>",
                    "activation_state": STATE_AWAITING_PAIRING,
                },
            },
        ),
    ]

    class SequencedSession(FakeSession):
        def request(self, method, url, **kwargs):
            self.calls.append({"method": method, "url": url, **kwargs})
            return responses.pop(0)

    _patch_installation_id(monkeypatch)
    session = SequencedSession(None)
    monkeypatch.setattr(
        "custom_components.aiva.api.async_get_clientsession",
        lambda hass: session,
    )
    client = AivaApiClient(hass, base_url="https://api.example.com")

    result = await client.start_activation(home_name="Casa Principal", plan="base")

    assert result.pairing_code == "<pairing-code>"
    assert result.home_name == "Casa Principal"
    assert result.plan == "premium"
    assert result.state == STATE_AWAITING_PAIRING
    assert result.home_id == "home-1"
    assert result.secret == "<redacted-secret>"
    assert [call["url"] for call in session.calls] == [
        "https://api.example.com/activation/request",
        "https://api.example.com/activation/pairing-code",
    ]


@pytest.mark.asyncio
async def test_start_activation_accepts_backend_valid_plan_override(hass, monkeypatch):
    """Use the backend plan when it returns a valid explicit value."""
    _patch_installation_id(monkeypatch)
    session = _patch_session(
        monkeypatch,
        FakeResponse(
            200,
            {
                "ok": True,
                "pairing_code": "<pairing-code>",
                "home_name": "Casa Principal",
                "plan": "premium",
                "activation_state": STATE_AWAITING_PAIRING,
            },
        ),
    )
    client = AivaApiClient(hass, base_url="https://api.example.com")

    result = await client.start_activation(home_name="Casa Principal", plan="base")

    assert result.plan == "premium"
    assert result.pairing_code == "<pairing-code>"
    assert len(session.calls) == 1


@pytest.mark.asyncio
async def test_start_activation_requires_home_id_and_secret_when_pairing_code_is_missing(
    hass, monkeypatch
):
    """Reject installed responses that cannot generate the second-step pairing code."""
    _patch_installation_id(monkeypatch)
    _patch_session(
        monkeypatch,
        FakeResponse(
            200,
            {
                "ok": True,
                "home_name": "Casa Principal",
                "plan": "premium",
                "activation_state": "installed",
            },
        ),
    )
    client = AivaApiClient(hass, base_url="https://api.example.com")

    with pytest.raises(AivaMissingRequiredDataError) as err:
        await client.start_activation(home_name="Casa Principal", plan="premium")

    assert "código de vinculación" in err.value.user_message


@pytest.mark.asyncio
async def test_start_activation_falls_back_to_legacy_endpoint_on_404(hass, monkeypatch):
    """Retry the legacy activation endpoint when the new one is not available."""
    responses = [
        FakeResponse(404, {"error": {"code": "not_found"}}),
        FakeResponse(
            200,
            {
                "ok": True,
                "pairing_code": "<pairing-code>",
                "home_name": "Casa Principal",
                "plan": "premium",
                "state": STATE_AWAITING_PAIRING,
            },
        ),
    ]

    class SequencedSession(FakeSession):
        def request(self, method, url, **kwargs):
            self.calls.append({"method": method, "url": url, **kwargs})
            return responses.pop(0)

    _patch_installation_id(monkeypatch)
    session = SequencedSession(None)
    monkeypatch.setattr(
        "custom_components.aiva.api.async_get_clientsession",
        lambda hass: session,
    )
    client = AivaApiClient(hass, base_url="https://api.example.com")

    result = await client.start_activation(
        home_name="Casa Principal",
        plan="premium",
    )

    assert result.pairing_code == "<pairing-code>"
    assert [call["url"] for call in session.calls] == [
        "https://api.example.com/activation/request",
        "https://api.example.com/pairing/start",
    ]


@pytest.mark.asyncio
async def test_get_activation_status_awaiting_payment(hass, monkeypatch):
    """Parse a pending payment activation status."""
    session = _patch_session(
        monkeypatch,
        FakeResponse(200, {"ok": True, "activation_state": STATE_AWAITING_PAYMENT}),
    )
    client = AivaApiClient(
        hass,
        base_url="https://api.example.com",
        home_id="home-1",
        secret="<redacted-secret>",
    )

    result = await client.get_activation_status()

    assert result.state == STATE_AWAITING_PAYMENT
    assert session.calls[0]["method"] == "get"
    assert session.calls[0]["url"] == "https://api.example.com/activation/status"
    assert session.calls[0]["params"] == {"home_id": "home-1"}
    assert session.calls[0]["headers"]["x-aiva-secret"] == "<redacted-secret>"


@pytest.mark.asyncio
async def test_start_activation_does_not_generate_pairing_code_when_awaiting_payment(
    hass, monkeypatch
):
    """Respect repeated activation/request responses that already passed pairing."""
    _patch_installation_id(monkeypatch)
    session = _patch_session(
        monkeypatch,
        FakeResponse(
            200,
            {
                "ok": True,
                "created": False,
                "home_id": "home-1",
                "installation_id": "ha-installation-1",
                "home_name": "Casa Principal",
                "secret": "<redacted-secret>",
                "plan": None,
                "activation_state": STATE_AWAITING_PAYMENT,
                "active": False,
                "next_step": "wait_payment",
            },
        ),
    )
    client = AivaApiClient(hass, base_url="https://api.example.com")

    result = await client.start_activation(home_name="Casa Principal", plan="premium")

    assert result.state == STATE_AWAITING_PAYMENT
    assert result.pairing_code is None
    assert result.home_id == "home-1"
    assert result.secret == "<redacted-secret>"
    assert len(session.calls) == 1
    assert session.calls[0]["url"] == "https://api.example.com/activation/request"


@pytest.mark.asyncio
async def test_start_activation_does_not_generate_pairing_code_when_active(
    hass, monkeypatch
):
    """Respect activation/request responses that are already active."""
    _patch_installation_id(monkeypatch)
    session = _patch_session(
        monkeypatch,
        FakeResponse(
            200,
            {
                "ok": True,
                "created": False,
                "home_id": "home-1",
                "home_name": "Casa Principal",
                "secret": "<redacted-secret>",
                "plan": "premium",
                "activation_state": STATE_ACTIVE,
                "active": True,
            },
        ),
    )
    client = AivaApiClient(hass, base_url="https://api.example.com")

    result = await client.start_activation(home_name="Casa Principal", plan="premium")

    assert result.state == STATE_ACTIVE
    assert result.pairing_code is None
    assert result.home_id == "home-1"
    assert result.secret == "<redacted-secret>"
    assert len(session.calls) == 1


@pytest.mark.asyncio
async def test_start_activation_accepts_suspended_without_pairing_generation(
    hass, monkeypatch
):
    """Accept the backend suspended state without treating it as invalid."""
    _patch_installation_id(monkeypatch)
    session = _patch_session(
        monkeypatch,
        FakeResponse(
            200,
            {
                "ok": True,
                "created": False,
                "home_id": "home-1",
                "home_name": "Casa Principal",
                "secret": "<redacted-secret>",
                "plan": "premium",
                "activation_state": STATE_SUSPENDED,
                "active": False,
            },
        ),
    )
    client = AivaApiClient(hass, base_url="https://api.example.com")

    result = await client.start_activation(home_name="Casa Principal", plan="premium")

    assert result.state == STATE_SUSPENDED
    assert result.pairing_code is None
    assert len(session.calls) == 1


@pytest.mark.asyncio
async def test_start_activation_raises_backend_client_error_with_message(hass, monkeypatch):
    """Expose useful backend messages for 4xx activation failures."""
    _patch_session(
        monkeypatch,
        FakeResponse(
            422,
            {
                "detail": "El plan seleccionado no está disponible",
                "error": {"code": "invalid_plan"},
            },
            headers={"x-request-id": "req-123"},
        ),
    )
    client = AivaApiClient(hass, base_url="https://api.example.com")

    with pytest.raises(AivaBackendClientError) as err:
        await client.start_activation(home_name="Casa Principal", plan="premium")

    assert err.value.user_message == "El plan seleccionado no está disponible"
    assert err.value.status == 422
    assert err.value.request_id == "req-123"


@pytest.mark.asyncio
async def test_start_activation_logs_invalid_activation_state_reason(
    hass, monkeypatch, caplog
):
    """Log safe diagnostics when activation/request returns an unusable state."""
    _patch_installation_id(monkeypatch)
    _patch_session(
        monkeypatch,
        FakeResponse(
            200,
            {
                "ok": True,
                "home_name": "Casa Principal",
                "plan": "premium",
                "activation_state": "success",
            },
        ),
    )
    client = AivaApiClient(hass, base_url="https://api.example.com")

    with caplog.at_level(logging.DEBUG, logger="custom_components.aiva.api"):
        with pytest.raises(AivaInvalidResponseError):
            await client.start_activation(home_name="Casa Principal", plan="premium")

    assert "AIVA activation state detected" in caplog.text
    assert "AIVA activation response contract" in caplog.text
    assert "endpoint=/activation/request" in caplog.text
    assert "status=200" in caplog.text
    assert "response_keys=['activation_state', 'home_name', 'ok', 'plan']" in caplog.text
    assert "root_keys=['activation_state', 'home_name', 'ok', 'plan']" in caplog.text
    assert "nested_keys={'data': None, 'result': None, 'activation': None}" in caplog.text
    assert "'state': None" in caplog.text
    assert "'activation_state': 'success'" in caplog.text
    assert "source=root" in caplog.text
    assert "raw_state=None" in caplog.text
    assert "raw_activation_state=success" in caplog.text
    assert "selected_raw_state=success" in caplog.text
    assert "reason=unknown_state" in caplog.text
    assert "normalized_state=success" in caplog.text
    assert "<redacted-secret>" not in caplog.text
    assert "<pairing-code>" not in caplog.text


@pytest.mark.asyncio
async def test_get_activation_status_active_requires_credentials(hass, monkeypatch):
    """Reject active responses without final credentials."""
    _patch_session(monkeypatch, FakeResponse(200, {"ok": True, "state": STATE_ACTIVE}))
    client = AivaApiClient(
        hass,
        base_url="https://api.example.com",
        home_id="home-1",
        secret="<redacted-secret>",
    )

    with pytest.raises(AivaMissingRequiredDataError):
        await client.get_activation_status()


@pytest.mark.asyncio
async def test_get_activation_status_active_success(hass, monkeypatch):
    """Parse final active status and keep known activation credentials."""
    _patch_session(
        monkeypatch,
        FakeResponse(
            200,
            {
                "ok": True,
                "state": STATE_ACTIVE,
                "home_name": "Casa Principal",
                "plan": "smart",
            },
        ),
    )
    client = AivaApiClient(
        hass,
        base_url="https://api.example.com",
        home_id="home-1",
        secret="<redacted-secret>",
    )

    result = await client.get_activation_status()

    assert result.state == STATE_ACTIVE
    assert result.home_id == "home-1"
    assert result.home_name == "Casa Principal"
    assert result.secret == "<redacted-secret>"
    assert result.plan == "smart"


@pytest.mark.asyncio
async def test_get_activation_status_active_flag_overrides_stale_state(
    hass, monkeypatch, caplog
):
    """Treat active=true from activation/status as the final payment confirmation."""
    _patch_session(
        monkeypatch,
        FakeResponse(
            200,
            {
                "ok": True,
                "activation_state": STATE_AWAITING_PAYMENT,
                "active": True,
                "home_name": "Casa Principal",
                "plan": "smart",
            },
        ),
    )
    client = AivaApiClient(
        hass,
        base_url="https://api.example.com",
        home_id="home-1",
        secret="<redacted-secret>",
    )

    with caplog.at_level(logging.DEBUG, logger="custom_components.aiva.api"):
        result = await client.get_activation_status()

    assert result.state == STATE_ACTIVE
    assert result.active is True
    assert result.home_id == "home-1"
    assert result.home_name == "Casa Principal"
    assert result.secret == "<redacted-secret>"
    assert "endpoint=/activation/status" in caplog.text
    assert "status=200" in caplog.text
    assert "'activation_state': 'awaiting_payment'" in caplog.text
    assert "'active': True" in caplog.text
    assert "active flag overrides state" in caplog.text
    assert "<redacted-secret>" not in caplog.text


@pytest.mark.asyncio
async def test_get_activation_status_active_flag_without_state(hass, monkeypatch):
    """Accept status responses that expose payment completion only via active=true."""
    _patch_session(
        monkeypatch,
        FakeResponse(
            200,
            {
                "ok": True,
                "active": True,
                "home_name": "Casa Principal",
            },
        ),
    )
    client = AivaApiClient(
        hass,
        base_url="https://api.example.com",
        home_id="home-1",
        secret="<redacted-secret>",
    )

    result = await client.get_activation_status()

    assert result.state == STATE_ACTIVE
    assert result.active is True
    assert result.home_id == "home-1"
    assert result.home_name == "Casa Principal"
    assert result.secret == "<redacted-secret>"


@pytest.mark.asyncio
async def test_get_home_settings_success(hass, monkeypatch):
    """Fetch and parse home settings without exposing them in config data."""
    session = _patch_session(
        monkeypatch,
        FakeResponse(
            200,
            {
                "ok": True,
                "settings": {
                    "language": "es",
                    "assistant_name": "AIVA",
                    "voice_provider": "ignored-for-now",
                    "voice_id": "voice-1",
                    "custom_prompt": "private prompt",
                    "country_code": "AR",
                    "locale": "es-AR",
                    "timezone": "America/Argentina/Buenos_Aires",
                    "response_style": "breve",
                },
            },
        ),
    )
    client = AivaApiClient(
        hass,
        base_url="https://api.example.com",
        home_id="home-1",
        secret="<redacted-secret>",
    )

    result = await client.get_home_settings()

    assert result.language == "es"
    assert result.assistant_name == "AIVA"
    assert result.custom_prompt == "private prompt"
    assert session.calls[0]["method"] == "get"
    assert session.calls[0]["url"] == "https://api.example.com/home/settings"
    assert session.calls[0]["headers"] == {"x-aiva-secret": "<redacted-secret>"}


@pytest.mark.asyncio
async def test_get_home_settings_invalid_response(hass, monkeypatch):
    """Reject malformed home settings responses."""
    _patch_session(
        monkeypatch,
        FakeResponse(200, {"ok": True, "settings": {"language": 123}}),
    )
    client = AivaApiClient(
        hass,
        base_url="https://api.example.com",
        home_id="home-1",
        secret="<redacted-secret>",
    )

    with pytest.raises(AivaInvalidResponseError):
        await client.get_home_settings()


@pytest.mark.asyncio
async def test_get_effective_entities_success(hass, monkeypatch):
    """Fetch and parse effective entities."""
    session = _patch_session(
        monkeypatch,
        FakeResponse(
            200,
            {
                "ok": True,
                "entities": [
                    {
                        "entity_id": "light.living",
                        "display_name": "Luz living",
                        "effective_area": "Living",
                        "alias": "luz principal",
                        "area_override": "Sala",
                        "is_allowed": True,
                        "is_visible": True,
                        "requires_confirmation": False,
                        "priority": 10,
                    }
                ],
            },
        ),
    )
    client = AivaApiClient(
        hass,
        base_url="https://api.example.com",
        home_id="home-1",
        secret="<redacted-secret>",
    )

    result = await client.get_effective_entities()

    assert len(result) == 1
    assert result[0].entity_id == "light.living"
    assert result[0].display_name == "Luz living"
    assert result[0].effective_area == "Living"
    assert result[0].is_allowed is True
    assert result[0].priority == 10
    assert session.calls[0]["url"] == "https://api.example.com/entities/effective"


@pytest.mark.asyncio
async def test_get_effective_entities_invalid_response(hass, monkeypatch):
    """Reject malformed effective entity responses."""
    _patch_session(
        monkeypatch,
        FakeResponse(200, {"ok": True, "entities": [{"display_name": "Sin ID"}]}),
    )
    client = AivaApiClient(
        hass,
        base_url="https://api.example.com",
        home_id="home-1",
        secret="<redacted-secret>",
    )

    with pytest.raises(AivaInvalidResponseError):
        await client.get_effective_entities()


@pytest.mark.asyncio
async def test_get_home_automations_success(hass, monkeypatch):
    """Fetch and parse home automations."""
    session = _patch_session(
        monkeypatch,
        FakeResponse(
            200,
            {
                "ok": True,
                "automations": [
                    {"id": "auto-1", "name": "Apagar luces", "enabled": True},
                    {
                        "automation_id": "auto-2",
                        "name": "Aviso puerta",
                        "enabled": False,
                    },
                ],
            },
        ),
    )
    client = AivaApiClient(
        hass,
        base_url="https://api.example.com",
        home_id="home-1",
        secret="<redacted-secret>",
    )

    result = await client.get_home_automations()

    assert [automation.automation_id for automation in result] == ["auto-1", "auto-2"]
    assert result[0].enabled is True
    assert result[1].enabled is False
    assert session.calls[0]["url"] == "https://api.example.com/home/automations"


@pytest.mark.asyncio
async def test_get_home_automations_invalid_response(hass, monkeypatch):
    """Reject malformed automation responses."""
    _patch_session(
        monkeypatch,
        FakeResponse(200, {"ok": True, "automations": [{"name": "Sin ID"}]}),
    )
    client = AivaApiClient(
        hass,
        base_url="https://api.example.com",
        home_id="home-1",
        secret="<redacted-secret>",
    )

    with pytest.raises(AivaInvalidResponseError):
        await client.get_home_automations()
