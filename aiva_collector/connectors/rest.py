"""Declarative GET-only REST profiles. No arbitrary code, SQL or remote schemas."""
import json
import time
from datetime import datetime, time as day_time, timedelta
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

import requests

from .base import AccessError, Connector, Reading, bounded_rows


def origin(url):
    u = urlsplit(url)
    return u.scheme.lower(), u.hostname, u.port or (443 if u.scheme == "https" else 80)


def secure_url(url, *, test_loopback=False):
    u = urlsplit(url)
    if u.username or u.password or u.fragment or u.query:
        raise AccessError("url_invalid", "La URL no debe contener credenciales, query ni fragmentos.")
    if u.scheme != "https" and not (test_loopback and u.scheme == "http" and u.hostname in {"127.0.0.1", "::1"}):
        raise AccessError("tls_required", "Usá HTTPS con certificado válido para acceder a la API.")
    if not u.hostname:
        raise AccessError("url_invalid", "Indicá una URL válida documentada por el proveedor.")
    return url


def field(value, path):
    for part in path.split('.') if path else []:
        if not isinstance(value, dict) or part not in value:
            raise AccessError("structure_changed", "La estructura cambió o el perfil no coincide. Revisá el mapeo antes de continuar.")
        value = value[part]
    return value


class RESTConnector(Connector):
    def __init__(self, profile, secrets=None, *, allow_loopback=False, refreshed=None):
        super().__init__(profile, secrets)
        self.base = secure_url(profile["base_url"], test_loopback=allow_loopback)
        self.session = requests.Session()
        self.session.trust_env = False  # no implicit .netrc credentials or proxy auth
        self.refreshed = refreshed
        self.allow_loopback = allow_loopback

    def read(self, window, *, sample=False):
        p = self.profile
        if p.get("semantics") != "whole_day_snapshot" or not p.get("date_filters"):
            raise AccessError("profile_required", "El proveedor debe documentar filtros de fecha y snapshots completos; una URL sola no basta.")
        url = urljoin(self.base.rstrip('/') + '/', p["path"])
        self._same_origin(url)
        params = {}
        filters = p["date_filters"]
        if filters.get("format", "date") == "datetime":
            tz = ZoneInfo(p["timezone"])
            start = datetime.combine(window.start, day_time.min, tz).isoformat()
            end = datetime.combine(window.end + timedelta(days=1), day_time.min, tz).isoformat()
        else:
            start = window.start.isoformat()
            end = (window.end + timedelta(days=1) if filters.get("end_exclusive") else window.end).isoformat()
        params.update({filters["from"]: start, filters["to"]: end})
        pagination = p.get("pagination", {"mode": "none"})
        mode = pagination.get("mode", "none")
        if mode not in {"none", "page", "cursor", "next_link"}:
            raise AccessError("pagination_invalid", "El perfil necesita una paginación documentada.")
        self.read_bytes = 0
        page_contents = set()
        page, seen, rows = int(pagination.get("first_page", 1)), set(), []
        max_pages = min(int(p.get("max_pages", 100)), 1000)
        started = time.monotonic()
        for _ in range(max_pages):
            if time.monotonic() - started > self.timeout:
                raise AccessError("timeout", "Se agotó el tiempo de lectura; reducí el período.")
            if mode == "page":
                params[pagination["parameter"]] = page
            marker = (url, json.dumps(params, sort_keys=True))
            if marker in seen:
                raise AccessError("pagination_loop", "La API repite páginas; corregí el perfil con el proveedor.")
            seen.add(marker)
            data = self._get(url, params)
            items = field(data, p.get("items_path", ""))
            if not isinstance(items, list) or any(not isinstance(r, dict) for r in items):
                raise AccessError("structure_changed", "La respuesta no contiene la lista de registros esperada.")
            if items and __import__("hashlib").sha256(json.dumps(items, sort_keys=True, default=str).encode()).hexdigest() in page_contents:
                raise AccessError("pagination_loop", "La API devolvió la misma página; no se enviaron datos parciales.")
            page_contents.add(__import__("hashlib").sha256(json.dumps(items, sort_keys=True, default=str).encode()).hexdigest())
            for item in items:
                rows.append({alias: field(item, path) for alias, path in p["fields"].items()})
                if len(rows) > self.max_rows:
                    raise AccessError("row_limit", "La API supera el límite de filas; reducí el período.")
            if sample and rows:
                return Reading(rows[:100])
            if mode == "none" or not items:
                break
            if mode == "page":
                if pagination.get("has_more_path"):
                    if not field(data, pagination["has_more_path"]):
                        break
                page += 1
            else:
                following = field(data, pagination["next_path"])
                if not following:
                    break
                if mode == "cursor":
                    params[pagination["parameter"]] = str(following)
                else:
                    url = urljoin(url, str(following))
                    self._same_origin(url)
                    params = {}
        else:
            raise AccessError("page_limit", "Se alcanzó el límite de páginas; no se confirmó cobertura ni se avanzó el cursor.")
        rows = bounded_rows(rows, self.max_rows)
        return Reading(rows, complete=p.get("complete_days") is True, empty_confirmed=p.get("empty_days_complete") is True)

    def _same_origin(self, url):
        u = urlsplit(url)
        if origin(url) != origin(self.base) or u.username or u.password or u.fragment:
            raise AccessError("origin_changed", "Se bloqueó un enlace a otro dominio. Revisá la paginación con el proveedor.")

    def _get(self, url, params):
        headers, auth = {"Accept": "application/json"}, None
        mode = self.profile.get("auth", "none")
        if mode in {"bearer", "oauth_pkce"}:
            if mode == "oauth_pkce":
                from ..oauth_access import refresh_if_needed
                self.secrets = refresh_if_needed(self.profile, self.secrets, self.refreshed)
            token = self.secrets.get("access_token")
            if not token:
                raise AccessError("credentials_required", "Falta el token de la API o renovar la autorización.")
            headers["Authorization"] = "Bearer " + token
        elif mode == "api_key":
            from .base import identifier
            name = self.profile.get("key_header", "X-API-Key")
            if not name.replace('-', '_').isidentifier() or not self.secrets.get("api_key"):
                raise AccessError("credentials_required", "Falta la clave API o el nombre de encabezado documentado.")
            headers[name] = self.secrets["api_key"]
        elif mode == "basic":
            if not self.secrets.get("username") or not self.secrets.get("password"):
                raise AccessError("credentials_required", "Falta usuario y contraseña específicos de la API.")
            auth = (self.secrets["username"], self.secrets["password"])
        elif mode != "none":
            raise AccessError("auth_unsupported", "El mecanismo de acceso requiere un perfil documentado.")
        try:
            with self.session.get(url, params=params, headers=headers, auth=auth, timeout=(5, self.timeout),
                                  verify=True, allow_redirects=False, stream=True) as response:
                if response.status_code == 401:
                    raise AccessError("authorization_expired", "Credenciales incorrectas o autorización vencida. Reemplazá o renová el acceso.")
                if response.status_code == 403:
                    raise AccessError("permission_denied", "El acceso no tiene permisos de lectura suficientes.")
                if response.status_code == 429 or response.status_code >= 500:
                    retry = response.headers.get("Retry-After", "60")
                    try:
                        seconds = int(retry)
                    except ValueError:
                        from email.utils import parsedate_to_datetime
                        from datetime import timezone
                        try:
                            seconds = int((parsedate_to_datetime(retry) - datetime.now(timezone.utc)).total_seconds())
                        except (ValueError, TypeError):
                            seconds = 60
                    raise AccessError("provider_temporary", "El proveedor pidió esperar. Se conserva el avance confirmado.", retry_after=min(max(seconds, 1), 86400))
                if response.status_code != 200:
                    raise AccessError("api_rejected", "La API rechazó la lectura. Revisá rutas y perfil; no se siguen redirecciones.")
                started = time.monotonic()
                raw = bytearray()
                for chunk in response.iter_content(65536):
                    if time.monotonic() - started > self.timeout:
                        raise AccessError("timeout", "Se agotó el tiempo máximo de respuesta.", retry_after=60)
                    self.read_bytes = getattr(self, "read_bytes", 0) + len(chunk)
                    if self.read_bytes > 50000000:
                        raise AccessError("memory_limit", "La lectura supera 50 MB; reducí período o página.")
                    raw.extend(chunk)
                    if len(raw) > min(int(self.profile.get("max_response_bytes", 10000000)), 20000000):
                        raise AccessError("response_limit", "La respuesta es demasiado grande; reducí el tamaño de página.")
                try:
                    return json.loads(raw)
                except (ValueError, UnicodeError):
                    raise AccessError("structure_changed", "La API no devolvió JSON válido.") from None
        except requests.exceptions.SSLError:
            raise AccessError("certificate_invalid", "El certificado no es válido. Pedí al proveedor que lo corrija.") from None
        except requests.RequestException:
            raise AccessError("service_unreachable", "No se pudo contactar al servicio. Revisá URL, red y disponibilidad.", retry_after=60) from None

    def close(self):
        self.session.close()
