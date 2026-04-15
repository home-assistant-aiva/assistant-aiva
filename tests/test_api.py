"""Tests for the AIVA API client."""

from __future__ import annotations

from aiohttp import ClientError
import pytest

from custom_components.aiva.api import (
    AivaApiClient,
    AivaCannotConnectError,
    AivaInvalidPairingCodeError,
    AivaInvalidResponseError,
    AivaMissingRequiredDataError,
)
from custom_components.aiva.const import (
    STATE_ACTIVE,
    STATE_AWAITING_PAIRING,
    STATE_AWAITING_PAYMENT,
)


class FakeResponse:
    """Minimal aiohttp response test double."""

    def __init__(self, status: int, payload):
        """Initialize the response."""
        self.status = status
        self._payload = payload

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

    with pytest.raises(AivaCannotConnectError):
        await client.validate_pairing_code("<pairing-code>", "Casa")


@pytest.mark.asyncio
async def test_validate_pairing_code_backend_unreachable(hass, monkeypatch):
    """Translate network failures into connection errors."""
    _patch_session(monkeypatch, ClientError("unreachable"))
    client = AivaApiClient(hass, base_url="http://127.0.0.1:8080")

    with pytest.raises(AivaCannotConnectError):
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
    """Start commercial activation and parse the generated pairing code."""
    session = _patch_session(
        monkeypatch,
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
    )
    client = AivaApiClient(hass, base_url="https://api.example.com")

    result = await client.start_activation(
        home_name="Casa Principal",
        plan="premium",
    )

    assert result.pairing_code == "<pairing-code>"
    assert result.state == STATE_AWAITING_PAIRING
    assert session.calls[0]["url"] == "https://api.example.com/pairing/start"
    assert session.calls[0]["json"] == {
        "home_name": "Casa Principal",
        "plan": "premium",
    }


@pytest.mark.asyncio
async def test_get_activation_status_awaiting_payment(hass, monkeypatch):
    """Parse a pending payment activation status."""
    session = _patch_session(
        monkeypatch,
        FakeResponse(200, {"ok": True, "state": STATE_AWAITING_PAYMENT}),
    )
    client = AivaApiClient(hass, base_url="https://api.example.com")

    result = await client.get_activation_status(pairing_code="<pairing-code>")

    assert result.state == STATE_AWAITING_PAYMENT
    assert session.calls[0]["url"] == "https://api.example.com/pairing/status"
    assert session.calls[0]["json"] == {"pairing_code": "<pairing-code>"}


@pytest.mark.asyncio
async def test_get_activation_status_active_requires_credentials(hass, monkeypatch):
    """Reject active responses without final credentials."""
    _patch_session(monkeypatch, FakeResponse(200, {"ok": True, "state": STATE_ACTIVE}))
    client = AivaApiClient(hass, base_url="https://api.example.com")

    with pytest.raises(AivaMissingRequiredDataError):
        await client.get_activation_status(pairing_code="<pairing-code>")


@pytest.mark.asyncio
async def test_get_activation_status_active_success(hass, monkeypatch):
    """Parse final active credentials from activation status."""
    _patch_session(
        monkeypatch,
        FakeResponse(
            200,
            {
                "ok": True,
                "state": STATE_ACTIVE,
                "home_id": "home-1",
                "home_name": "Casa Principal",
                "secret": "<redacted-secret>",
                "plan": "smart",
            },
        ),
    )
    client = AivaApiClient(hass, base_url="https://api.example.com")

    result = await client.get_activation_status(pairing_code="<pairing-code>")

    assert result.state == STATE_ACTIVE
    assert result.home_id == "home-1"
    assert result.home_name == "Casa Principal"
    assert result.secret == "<redacted-secret>"
    assert result.plan == "smart"
