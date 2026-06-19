from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests


DEFAULT_BASE_URL = "http://127.0.0.1:8080"
DEFAULT_BACKEND_ENV = Path("/opt/aiva-backend/.env")
DEFAULT_PREFIX = "Demo Integracion Collector AIVA"


class CleanupError(RuntimeError):
    pass


@dataclass(frozen=True)
class CleanupPlan:
    total_commerces: int
    demos: list[dict[str, Any]]
    kept: list[dict[str, Any]]
    candidates: list[dict[str, Any]]
    inactive: list[dict[str, Any]]
    truncated: bool
    max_to_deactivate: int


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
        raise CleanupError("No se pudo obtener AIVA_INTERNAL_SECRET desde el entorno ni desde /opt/aiva-backend/.env")
    return value


def mask_sensitive(text: str, secrets: list[str]) -> str:
    masked = text
    for secret in secrets:
        if secret:
            masked = masked.replace(secret, "[MASKED]")
    masked = re.sub(r"(Bearer\s+)[A-Za-z0-9._~+/=-]+", r"\1[MASKED]", masked)
    masked = re.sub(r"(x-aiva-secret['\"]?\s*[:=]\s*['\"]?)[^'\"\s,}]+", r"\1[MASKED]", masked, flags=re.I)
    masked = re.sub(r"(collector_token['\"]?\s*[:=]\s*['\"]?)[^'\"\s,}]+", r"\1[MASKED]", masked, flags=re.I)
    masked = re.sub(r"(token['\"]?\s*[:=]\s*['\"]?)[^'\"\s,}]+", r"\1[MASKED]", masked, flags=re.I)
    return masked


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


def extract_businesses(payload: Any) -> list[dict[str, Any]]:
    businesses = _deep_find(payload, {"businesses", "items", "data"})
    if not isinstance(businesses, list):
        businesses = payload if isinstance(payload, list) else []
    return [item for item in businesses if isinstance(item, dict)]


def commerce_id_for(business: dict[str, Any]) -> str:
    value = business.get("commerce_id") or business.get("id")
    if value in (None, ""):
        raise CleanupError("Comercio sin commerce_id en respuesta backend")
    return str(value)


def is_demo_business(business: dict[str, Any], prefix: str = DEFAULT_PREFIX) -> bool:
    return str(business.get("display_name") or "").startswith(prefix)


def is_active_business(business: dict[str, Any]) -> bool:
    if str(business.get("activation_state") or "").lower() == "inactive":
        return False
    if business.get("is_enabled") is False:
        return False
    return True


def _business_sort_key(business: dict[str, Any]) -> tuple[str, str]:
    timestamp = business.get("created_at") or business.get("updated_at") or ""
    return str(timestamp), commerce_id_for(business)


def sorted_demo_businesses(businesses: list[dict[str, Any]], prefix: str = DEFAULT_PREFIX) -> list[dict[str, Any]]:
    demos = [business for business in businesses if is_demo_business(business, prefix)]
    return sorted(demos, key=_business_sort_key, reverse=True)


def build_cleanup_plan(
    businesses: list[dict[str, Any]],
    *,
    prefix: str = DEFAULT_PREFIX,
    keep_latest: int = 1,
    keep_commerce_ids: set[str] | None = None,
    max_to_deactivate: int = 20,
    include_inactive: bool = False,
) -> CleanupPlan:
    if keep_latest < 0:
        raise CleanupError("--keep-latest no puede ser negativo")
    if max_to_deactivate < 0:
        raise CleanupError("--max-to-deactivate no puede ser negativo")

    keep_commerce_ids = keep_commerce_ids or set()
    demos = sorted_demo_businesses(businesses, prefix)
    latest_keep_ids = {commerce_id_for(item) for item in demos[:keep_latest]}
    keep_ids = latest_keep_ids | keep_commerce_ids
    kept = [item for item in demos if commerce_id_for(item) in keep_ids]

    raw_candidates = [item for item in demos if commerce_id_for(item) not in keep_ids and is_active_business(item)]
    inactive = [item for item in demos if commerce_id_for(item) not in keep_ids and not is_active_business(item)]
    candidates = raw_candidates[:max_to_deactivate]
    truncated = len(raw_candidates) > len(candidates)
    visible_demos = demos if include_inactive else [item for item in demos if is_active_business(item)]
    visible_inactive = inactive if include_inactive else []
    return CleanupPlan(
        total_commerces=len(businesses),
        demos=visible_demos,
        kept=kept,
        candidates=candidates,
        inactive=visible_inactive,
        truncated=truncated,
        max_to_deactivate=max_to_deactivate,
    )


def _request_json(
    method: str,
    url: str,
    *,
    secret: str,
    expected: tuple[int, ...] = (200, 201),
) -> Any:
    try:
        response = requests.request(method, url, headers={"x-aiva-secret": secret}, timeout=20)
    except requests.RequestException as exc:
        raise CleanupError(f"Backend no disponible: {exc}") from exc
    if response.status_code not in expected:
        detail = response.text[:300]
        raise CleanupError(f"Backend respondio HTTP {response.status_code} en {method} {url}: {detail}")
    if not response.content:
        return {}
    try:
        return response.json()
    except ValueError as exc:
        raise CleanupError(f"Respuesta backend no es JSON en {method} {url}") from exc


def list_businesses(base_url: str, secret: str) -> list[dict[str, Any]]:
    payload = _request_json("GET", f"{base_url.rstrip('/')}/admin/commerce/businesses", secret=secret)
    return extract_businesses(payload)


def deactivate_business(base_url: str, secret: str, commerce_id: str) -> dict[str, Any]:
    return _request_json(
        "POST",
        f"{base_url.rstrip('/')}/admin/commerce/businesses/{commerce_id}/deactivate",
        secret=secret,
    )


def _safe_business_view(business: dict[str, Any]) -> dict[str, Any]:
    return {
        "commerce_id": commerce_id_for(business),
        "display_name": str(business.get("display_name") or ""),
        "created_at": business.get("created_at"),
        "updated_at": business.get("updated_at"),
        "activation_state": business.get("activation_state"),
        "is_enabled": business.get("is_enabled"),
    }


def plan_to_json(plan: CleanupPlan, *, mode: str, results: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "mode": mode,
        "total_commerces": plan.total_commerces,
        "total_demos_found": len(plan.demos),
        "kept": [_safe_business_view(item) for item in plan.kept],
        "candidates": [_safe_business_view(item) for item in plan.candidates],
        "inactive_visible": [_safe_business_view(item) for item in plan.inactive],
        "to_deactivate_count": len(plan.candidates),
        "max_to_deactivate": plan.max_to_deactivate,
        "max_to_deactivate_reached": plan.truncated,
        "results": results or [],
    }


def print_human_plan(plan: CleanupPlan, *, mode: str, results: list[dict[str, Any]] | None = None) -> None:
    print(f"modo: {mode}")
    print(f"total_commerces_leidos: {plan.total_commerces}")
    print(f"total_demos_encontrados: {len(plan.demos)}")
    print(f"demos_mantenidos: {len(plan.kept)}")
    for item in plan.kept:
        view = _safe_business_view(item)
        print(f"  keep {view['commerce_id']} | {view['display_name']}")
    print(f"demos_candidatos_a_desactivar: {len(plan.candidates)}")
    for item in plan.candidates:
        view = _safe_business_view(item)
        print(f"  candidate {view['commerce_id']} | {view['display_name']}")
    if plan.inactive:
        print(f"demos_inactivos_visibles: {len(plan.inactive)}")
        for item in plan.inactive:
            view = _safe_business_view(item)
            print(f"  inactive {view['commerce_id']} | {view['display_name']}")
    print(f"cantidad_a_desactivar: {len(plan.candidates)}")
    if plan.truncated:
        print(f"max_to_deactivate_alcanzado: {plan.max_to_deactivate}")
    if results:
        print("resultados:")
        for result in results:
            print(f"  {result['commerce_id']}: {result['status']}")


def run_cleanup(
    *,
    base_url: str,
    secret: str,
    confirm: bool,
    keep_latest: int,
    keep_commerce_ids: set[str],
    prefix: str,
    max_to_deactivate: int,
    include_inactive: bool,
) -> tuple[CleanupPlan, list[dict[str, Any]]]:
    businesses = list_businesses(base_url, secret)
    plan = build_cleanup_plan(
        businesses,
        prefix=prefix,
        keep_latest=keep_latest,
        keep_commerce_ids=keep_commerce_ids,
        max_to_deactivate=max_to_deactivate,
        include_inactive=include_inactive,
    )
    results: list[dict[str, Any]] = []
    if confirm:
        for business in plan.candidates:
            commerce_id = commerce_id_for(business)
            deactivate_business(base_url, secret, commerce_id)
            results.append({"commerce_id": commerce_id, "status": "deactivated"})
    return plan, results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cleanup seguro de comercios demo del Collector AIVA")
    parser.add_argument("--dry-run", action="store_true", help="No modifica nada. Es el modo por defecto.")
    parser.add_argument("--confirm", action="store_true", help="Aplica la desactivacion de candidatos.")
    parser.add_argument("--keep-latest", type=int, default=1)
    parser.add_argument("--keep-commerce-id", action="append", default=[])
    parser.add_argument("--prefix", default=DEFAULT_PREFIX)
    parser.add_argument("--max-to-deactivate", type=int, default=20)
    parser.add_argument("--include-inactive", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--base-url", default=os.getenv("BASE_URL") or os.getenv("AIVA_BACKEND_URL") or DEFAULT_BASE_URL)
    args = parser.parse_args(argv)

    if args.confirm and args.dry_run:
        parser.error("--confirm y --dry-run no pueden usarse juntos")

    mode = "confirm" if args.confirm else "dry-run"
    secret = ""
    try:
        secret = load_internal_secret()
        plan, results = run_cleanup(
            base_url=args.base_url,
            secret=secret,
            confirm=args.confirm,
            keep_latest=args.keep_latest,
            keep_commerce_ids=set(args.keep_commerce_id),
            prefix=args.prefix,
            max_to_deactivate=args.max_to_deactivate,
            include_inactive=args.include_inactive,
        )
    except CleanupError as exc:
        print(f"Error: {mask_sensitive(str(exc), [secret])}", file=sys.stderr)
        return 2

    if args.as_json:
        print(mask_sensitive(json.dumps(plan_to_json(plan, mode=mode, results=results), indent=2, ensure_ascii=True), [secret]))
    else:
        print_human_plan(plan, mode=mode, results=results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
