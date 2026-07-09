from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE_URL = "http://127.0.0.1:8080"
DEFAULT_BACKEND_ENV = Path("/opt/aiva-backend/.env")
DEMO_NAME = "Demo Integracion Collector AIVA"
DEMO_COLLECTOR_NAME = "Collector Demo Integracion"
TOKEN_ENV = "AIVA_COLLECTOR_TOKEN"


class IntegrationError(RuntimeError):
    pass


def _read_dotenv_value(path: Path, key: str) -> str | None:
    if not path.exists():
        return None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() != key:
            continue
        value = value.strip().strip('"').strip("'")
        return value or None
    return None


def load_internal_secret(env_path: Path = DEFAULT_BACKEND_ENV) -> str:
    value = os.getenv("AIVA_INTERNAL_SECRET") or _read_dotenv_value(env_path, "AIVA_INTERNAL_SECRET")
    if not value:
        raise IntegrationError(
            "No se pudo obtener AIVA_INTERNAL_SECRET desde el entorno ni desde /opt/aiva-backend/.env"
        )
    return value


def mask_sensitive(text: str, secrets: list[str]) -> str:
    masked = text
    for secret in secrets:
        if secret:
            masked = masked.replace(secret, "[MASKED]")
    masked = re.sub(r"(Bearer\s+)[A-Za-z0-9._~+/=-]+", r"\1[MASKED]", masked)
    masked = re.sub(r"(collector_token['\"]?\s*[:=]\s*['\"]?)[^'\"\s,}]+", r"\1[MASKED]", masked)
    return masked


def idempotency_key_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def is_demo_business(business: dict[str, Any]) -> bool:
    return str(business.get("display_name") or "").startswith(DEMO_NAME)


def _business_sort_key(business: dict[str, Any]) -> str:
    return str(business.get("created_at") or business.get("updated_at") or business.get("commerce_id") or "")


def find_demo_businesses(payload: Any) -> list[dict[str, Any]]:
    businesses = _deep_find(payload, {"businesses", "items", "data"})
    if not isinstance(businesses, list):
        businesses = payload if isinstance(payload, list) else []
    demos = [item for item in businesses if isinstance(item, dict) and is_demo_business(item)]
    return sorted(demos, key=_business_sort_key, reverse=True)


def latest_demo_business(payload: Any) -> dict[str, Any] | None:
    demos = find_demo_businesses(payload)
    return demos[0] if demos else None


def _deep_find(data: Any, keys: set[str]) -> Any:
    if isinstance(data, dict):
        for key, value in data.items():
            if key in keys and value not in (None, ""):
                return value
        for value in data.values():
            found = _deep_find(value, keys)
            if found not in (None, ""):
                return found
    elif isinstance(data, list):
        for item in data:
            found = _deep_find(item, keys)
            if found not in (None, ""):
                return found
    return None


def extract_required(data: Any, keys: set[str], label: str) -> str:
    value = _deep_find(data, keys)
    if value in (None, ""):
        raise IntegrationError(f"No se pudo leer {label} en respuesta backend")
    return str(value)


def recommendations_count(data: Any) -> int:
    explicit = _deep_find(data, {"recommendations_count", "recommendation_count", "count"})
    if isinstance(explicit, int):
        return explicit
    if isinstance(explicit, str) and explicit.isdigit():
        return int(explicit)
    recommendations = _deep_find(data, {"recommendations", "items", "data"})
    if isinstance(recommendations, list):
        return len(recommendations)
    if isinstance(data, list):
        return len(data)
    return 0


def write_temp_config(base_url: str, commerce_id: str, collector_id: str) -> Path:
    example_path = PROJECT_ROOT / "configs" / "example_config.json"
    data = json.loads(example_path.read_text(encoding="utf-8"))
    data.update(
        {
            "backend_url": base_url,
            "commerce_id": commerce_id,
            "collector_id": collector_id,
            "input_dir": "samples/input",
            "processed_dir": "samples/processed",
            "error_dir": "samples/error",
            "output_dir": "samples/output",
            "state_dir": "state",
            "log_file": "logs/aiva_collector.log",
            "collector_token_env": TOKEN_ENV,
            "move_processed_files": False,
        }
    )
    data.pop("collector_token", None)
    fd, raw_path = tempfile.mkstemp(prefix="aiva_collector_integration_", suffix=".json")
    path = Path(raw_path)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=True)
        fh.write("\n")
    return path


def _request_json(
    method: str,
    url: str,
    *,
    secret: str | None = None,
    payload: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    expected: tuple[int, ...] = (200, 201),
) -> Any:
    headers = {"x-aiva-secret": secret} if secret else {}
    try:
        response = requests.request(method, url, json=payload, params=params, headers=headers, timeout=20)
    except requests.RequestException as exc:
        raise IntegrationError(f"Backend no disponible: {exc}") from exc
    if response.status_code not in expected:
        detail = response.text[:400]
        raise IntegrationError(f"Backend respondio HTTP {response.status_code} en {method} {url}: {detail}")
    if not response.content:
        return {}
    try:
        return response.json()
    except ValueError as exc:
        raise IntegrationError(f"Respuesta backend no es JSON en {method} {url}") from exc


def run_collector_command(args: list[str], *, token: str | None = None, secrets: list[str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if token:
        env[TOKEN_ENV] = token
    else:
        env.pop(TOKEN_ENV, None)
    command = [sys.executable, "-m", "aiva_collector.cli", *args]
    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        safe_output = mask_sensitive((result.stdout or "") + (result.stderr or ""), secrets)
        raise IntegrationError(f"Comando collector fallo: {' '.join(command)}\n{safe_output.strip()}")
    return result


def run_send(config_path: Path, collector_token: str, secrets: list[str]) -> str:
    env = os.environ.copy()
    env[TOKEN_ENV] = collector_token
    command = [sys.executable, "-m", "aiva_collector.cli", "run-once", "--config", str(config_path), "--send"]
    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    output = mask_sensitive((result.stdout or "") + (result.stderr or ""), secrets)
    if result.returncode == 0:
        return "sent"
    if "duplicate_summary" in output or "Summary duplicado" in output:
        return "duplicate_summary"
    if "Comercio sin pago" in output or "HTTP 402" in output:
        raise IntegrationError("El envio fallo con 402: comercio no activo, sin pago o suspendido")
    if "Token invalido" in output or "no autorizado" in output or "HTTP 401" in output or "HTTP 403" in output:
        raise IntegrationError("El envio fallo con 401/403: problema de token, collector o comercio inactivo")
    raise IntegrationError(f"run-once --send fallo\n{output.strip()}")


def _create_demo_business(admin_base: str, secret: str) -> str:
    commerce = _request_json(
        "POST",
        admin_base,
        secret=secret,
        payload={
            "display_name": DEMO_NAME,
            "legal_name": DEMO_NAME,
            "timezone": "America/Argentina/Buenos_Aires",
        },
    )
    return extract_required(commerce, {"commerce_id", "id"}, "commerce_id")


def _get_or_create_demo_business(
    base_url: str,
    admin_base: str,
    secret: str,
    *,
    reuse_latest_demo: bool,
    force_new_demo: bool,
) -> tuple[str, bool]:
    if reuse_latest_demo and not force_new_demo:
        listed = _request_json("GET", admin_base, secret=secret)
        latest = latest_demo_business(listed)
        if latest:
            commerce_id = extract_required(latest, {"commerce_id", "id"}, "commerce_id")
            active = str(latest.get("activation_state") or "").lower() == "active" and bool(latest.get("is_enabled", True))
            if not active:
                _request_json("POST", f"{admin_base}/{commerce_id}/activate", secret=secret)
                print("commerce: reactivated")
            print(f"commerce_id: {commerce_id}")
            print("commerce: reused_latest_demo")
            return commerce_id, True

    commerce_id = _create_demo_business(admin_base, secret)
    print(f"commerce_id: {commerce_id}")
    _request_json("POST", f"{admin_base}/{commerce_id}/activate", secret=secret)
    print("commerce: activated")
    return commerce_id, False


def _create_demo_collector(admin_base: str, secret: str, commerce_id: str) -> tuple[str, str]:
    collector = _request_json(
        "POST",
        f"{admin_base}/{commerce_id}/collectors",
        secret=secret,
        payload={"name": DEMO_COLLECTOR_NAME},
    )
    collector_id = extract_required(collector, {"collector_id", "id"}, "collector_id")
    collector_token = extract_required(collector, {"collector_token", "token"}, "collector_token")
    print(f"collector_id: {collector_id}")
    return collector_id, collector_token


def _ensure_demo_collector(admin_base: str, secret: str, commerce_id: str, *, reused_business: bool) -> tuple[str, str]:
    if reused_business:
        detail = _request_json("GET", f"{admin_base}/{commerce_id}", secret=secret)
        collectors = _deep_find(detail, {"collectors"})
        has_demo_collector = any(
            isinstance(item, dict) and item.get("name") == DEMO_COLLECTOR_NAME
            for item in (collectors if isinstance(collectors, list) else [])
        )
        if has_demo_collector:
            print("collector: existing demo collector found but token is not recoverable; creating a fresh collector")
    return _create_demo_collector(admin_base, secret, commerce_id)


def deactivate_old_demos(base_url: str, current_commerce_id: str | None, secret: str) -> int:
    print("deactivate_old_demos: deprecated_noop")
    print("cleanup: usar scripts/cleanup_demo_businesses.sh --dry-run / --confirm")
    return 0


def _audit_summary(base_url: str, secret: str, commerce_id: str) -> dict[str, Any]:
    admin_base = f"{base_url}/admin/commerce/businesses"
    summaries = _request_json(
        "GET",
        f"{admin_base}/{commerce_id}/ingestion-summaries",
        secret=secret,
        params={"limit": 5, "include_metadata": "false"},
    )
    audit = _request_json("GET", f"{admin_base}/{commerce_id}/audit", secret=secret)
    audit_payload = audit.get("audit", audit) if isinstance(audit, dict) else {}
    latest = summaries.get("summaries", [None])[0] if isinstance(summaries, dict) and summaries.get("summaries") else None
    print("audit: checked")
    print(f"summaries_count: {audit_payload.get('summaries_count', 0)}")
    if isinstance(latest, dict):
        print(f"latest_summary_period: {latest.get('period_start')} to {latest.get('period_end')}")
        print(f"latest_summary_product_count: {latest.get('product_count')}")
    print(f"recommendations_count: {audit_payload.get('recommendations_count', 0)}")
    print(f"reports_count: {audit_payload.get('reports_count', 0)}")
    print(f"last_report_id: {audit_payload.get('last_report_id')}")
    return {"summaries": summaries, "audit": audit_payload}


def update_demo_state(config_path: Path, *, report_id: str | None, idempotency_confirmed: bool) -> None:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    state_dir = Path(str(config.get("state_dir") or "state"))
    if not state_dir.is_absolute():
        state_dir = PROJECT_ROOT / state_dir
    state_path = state_dir / "collector_state.json"
    if not state_path.exists():
        return
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["last_backend_report_id"] = report_id
    state["idempotency_confirmed"] = bool(idempotency_confirmed)
    for forbidden in ("collector_token", "token", "authorization", "secret", "token_hash"):
        state.pop(forbidden, None)
    state_path.write_text(json.dumps(state, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def run_integration(
    base_url: str,
    *,
    reuse_latest_demo: bool = False,
    test_idempotency: bool = False,
    deactivate_old_demos_flag: bool = False,
    force_new_demo: bool = False,
) -> dict[str, Any]:
    base_url = base_url.rstrip("/")
    secret = load_internal_secret()
    admin_base = f"{base_url}/admin/commerce/businesses"
    print(f"Backend base_url: {base_url}")

    _request_json("GET", f"{base_url}/health")
    print("health: ok")

    commerce_id, reused_business = _get_or_create_demo_business(
        base_url,
        admin_base,
        secret,
        reuse_latest_demo=reuse_latest_demo,
        force_new_demo=force_new_demo,
    )
    collector_id, collector_token = _ensure_demo_collector(
        admin_base,
        secret,
        commerce_id,
        reused_business=reused_business,
    )

    config_path = write_temp_config(base_url, commerce_id, collector_id)
    print(f"config_temporal: {config_path}")

    secrets = [secret, collector_token]
    run_collector_command(["validate", "--config", str(config_path)], secrets=secrets)
    print("collector validate: ok")
    run_collector_command(["status", "--config", str(config_path)], token=collector_token, secrets=secrets)
    print("collector status: ok")
    print("run: start")
    summary_status = run_send(config_path, collector_token, secrets)
    print(f"summary_status: {summary_status}")

    first_audit = _audit_summary(base_url, secret, commerce_id)
    idempotency_confirmed = False
    second_send_status = None
    if test_idempotency:
        second_send_status = run_send(config_path, collector_token, secrets)
        print(f"second_send_status: {second_send_status}")
        second_audit = _audit_summary(base_url, secret, commerce_id)
        before_count = int(first_audit["audit"].get("summaries_count") or 0)
        after_count = int(second_audit["audit"].get("summaries_count") or 0)
        idempotency_confirmed = second_send_status == "duplicate_summary" and after_count == before_count
        print(f"idempotency_confirmed: {str(idempotency_confirmed).lower()}")
        if not idempotency_confirmed:
            raise IntegrationError("No se confirmo idempotencia: el segundo envio no devolvio duplicate_summary sin duplicar")

    recommendations = _request_json("GET", f"{admin_base}/{commerce_id}/recommendations", secret=secret)
    rec_count = recommendations_count(recommendations)
    if rec_count < 1:
        raise IntegrationError("El backend no devolvio recomendaciones generadas para el comercio demo")
    print(f"recommendations_count: {rec_count}")

    report = _request_json("POST", f"{admin_base}/{commerce_id}/reports/generate", secret=secret)
    report_id = extract_required(report, {"report_id", "id"}, "report_id")
    report_status = str(_deep_find(report, {"status"}) or "")
    report_text = str(_deep_find(report, {"report_text", "text", "content"}) or "")
    if report_status != "generated" or not report_text.strip():
        raise IntegrationError("El reporte no fue generado correctamente o no contiene texto")
    print(f"report_id: {report_id}")
    print("report: generated")

    latest = _request_json("GET", f"{admin_base}/{commerce_id}/latest-report", secret=secret)
    latest_report_id = extract_required(latest, {"report_id", "id"}, "latest report_id")
    if latest_report_id != report_id:
        raise IntegrationError("latest-report no coincide con el report_id generado")
    print("latest_report: verified")
    update_demo_state(config_path, report_id=report_id, idempotency_confirmed=idempotency_confirmed)
    final_audit = _audit_summary(base_url, secret, commerce_id)
    if deactivate_old_demos_flag:
        print("deactivate_old_demos: deprecated_noop")
        print("cleanup: usar scripts/cleanup_demo_businesses.sh --dry-run / --confirm")
    print("telegram: not_sent")
    print("secrets: not_printed")

    return {
        "commerce_id": commerce_id,
        "collector_id": collector_id,
        "first_send_status": summary_status,
        "second_send_status": second_send_status,
        "summary_status": summary_status,
        "idempotency_confirmed": idempotency_confirmed,
        "summaries_count": final_audit["audit"].get("summaries_count"),
        "recommendations_count": rec_count,
        "report_id": report_id,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AIVA Collector backend integration demo")
    parser.add_argument("--base-url", default=os.getenv("AIVA_BACKEND_URL", DEFAULT_BASE_URL))
    parser.add_argument("--reuse-latest-demo", action="store_true")
    parser.add_argument("--test-idempotency", action="store_true")
    parser.add_argument("--deactivate-old-demos", action="store_true")
    parser.add_argument("--force-new-demo", action="store_true")
    args = parser.parse_args(argv)
    if args.deactivate_old_demos:
        print("--deactivate-old-demos ya no ejecuta limpieza desde la integracion.")
        print("Usa: bash scripts/cleanup_demo_businesses.sh --dry-run")
        print("Luego, si el dry-run es correcto: bash scripts/cleanup_demo_businesses.sh --confirm --keep-latest 1")
        return 0
    try:
        result = run_integration(
            args.base_url,
            reuse_latest_demo=args.reuse_latest_demo,
            test_idempotency=args.test_idempotency,
            deactivate_old_demos_flag=args.deactivate_old_demos,
            force_new_demo=args.force_new_demo,
        )
    except IntegrationError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    print("integration_demo: ok")
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
