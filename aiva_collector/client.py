from __future__ import annotations

from typing import Any

import requests

from .config import CollectorConfig
from .errors import BackendError
from .summarizer import idempotency_key


def _headers(config: CollectorConfig, idem_key: str | None = None) -> dict[str, str]:
    token = config.token
    if not token:
        raise BackendError(f"Falta token: exportar {config.collector_token_env}")
    headers = {
        "Authorization": f"Bearer {token}",
        "X-AIVA-Collector-Id": config.collector_id,
    }
    if idem_key:
        headers["X-Idempotency-Key"] = idem_key
    return headers


def _safe_error(response: requests.Response) -> BackendError:
    try:
        detail = response.json()
    except ValueError:
        detail = response.text[:300]
    status = response.status_code
    if status == 400:
        message = f"Solicitud invalida al backend: {detail}"
    elif status == 401:
        message = "Token invalido o no autorizado"
    elif status == 402:
        message = "Comercio sin pago o suspendido"
    elif status == 403:
        message = "Comercio inactivo o deshabilitado"
    elif status == 409:
        message = "Summary duplicado (duplicate_summary)"
    else:
        message = f"Backend respondio HTTP {status}: {detail}"
    return BackendError(message, status_code=status)


class CollectorClient:
    def __init__(self, config: CollectorConfig, timeout: int = 20) -> None:
        self.config = config
        self.timeout = timeout

    def post_status(self, status: str, message: str | None = None) -> dict[str, Any]:
        payload = {
            "commerce_id": self.config.commerce_id,
            "collector_id": self.config.collector_id,
            "status": status,
            "version": self.config.collector_version,
        }
        if message:
            payload["error_message"] = message[:240]
        response = requests.post(
            f"{self.config.backend_url}/commerce/collector/status",
            json=payload,
            headers=_headers(self.config),
            timeout=self.timeout,
        )
        if response.status_code not in (200, 201):
            raise _safe_error(response)
        data = response.json() if response.content else {}
        data["_http_status_code"] = response.status_code
        return data

    def service_status(self) -> dict[str, Any]:
        response = requests.get(
            f"{self.config.backend_url}/commerce/collector/service-status",
            params={"commerce_id": self.config.commerce_id, "collector_id": self.config.collector_id},
            headers=_headers(self.config),
            timeout=self.timeout,
        )
        if response.status_code not in (200, 201):
            raise _safe_error(response)
        return response.json() if response.content else {}

    def send_summary(self, summary: dict[str, Any]) -> dict[str, Any]:
        idem_key = idempotency_key(summary)
        response = requests.post(
            f"{self.config.backend_url}/commerce/collector/summaries",
            json=summary,
            headers=_headers(self.config, idem_key),
            timeout=self.timeout,
        )
        if response.status_code not in (200, 201):
            raise _safe_error(response)
        return response.json() if response.content else {}
