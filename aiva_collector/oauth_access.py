"""Native authorization code + PKCE; loopback listener is local, temporary and state-bound."""
import base64
import hashlib
import secrets
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode

import requests

from .connectors.base import AccessError
from .connectors.rest import secure_url


def _token(profile, data):
    endpoint = secure_url(profile["oauth"]["token_url"])
    session = requests.Session()
    session.trust_env = False
    try:
        with session.post(endpoint, data=data, timeout=(5, 20), verify=True, allow_redirects=False, stream=True) as response:
            if response.status_code != 200:
                raise AccessError("authorization_expired", "El proveedor rechazó la autorización. Revisá registro, scopes o revocación y volvé a autorizar.")
            body = bytearray()
            for chunk in response.iter_content(4096):
                body.extend(chunk)
                if len(body) > 65536:
                    raise AccessError("oauth_response_invalid", "La respuesta de autorización supera el límite permitido.")
            import json
            result = json.loads(body)
            if not result.get("access_token") or str(result.get("token_type", "Bearer")).lower() != "bearer":
                raise AccessError("oauth_response_invalid", "El proveedor no devolvió un token Bearer utilizable.")
            return {"access_token": result["access_token"], "refresh_token": result.get("refresh_token"),
                    "expires_at": time.time() + max(0, int(result.get("expires_in", 300))) - 30}
    except requests.RequestException:
        raise AccessError("oauth_unreachable", "No se pudo contactar al proveedor de autorización; revisá TLS y red.") from None
    finally:
        session.close()


def authorize(profile):
    oauth = profile.get("oauth", {})
    if not all(oauth.get(k) for k in ("client_id", "authorization_url", "token_url", "scopes")):
        raise AccessError("oauth_registration_required", "Pedí al proveedor el registro de aplicación pública, client_id, scopes y URLs OAuth; no se admite client_secret.")
    auth_url = secure_url(oauth["authorization_url"])
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    state = secrets.token_urlsafe(32)
    response = {}
    class Callback(BaseHTTPRequestHandler):
        def do_GET(self):
            from urllib.parse import urlsplit
            parsed = urlsplit(self.path)
            args = parse_qs(parsed.query)
            valid = parsed.path == '/callback' and args.get('state') == [state] and bool(args.get('code'))
            self.send_response(200 if valid else 400)
            self.end_headers()
            self.wfile.write(b"AIVA: authorization received. You may close this window." if valid else b"Invalid authorization state.")
            if valid:
                response['code'] = args['code'][0]
        def log_message(self, *args):
            pass
    with HTTPServer(('127.0.0.1', 0), Callback) as server:
        server.timeout = 1
        redirect = f'http://127.0.0.1:{server.server_port}/callback'
        webbrowser.open(auth_url + '?' + urlencode({"response_type": "code", "client_id": oauth['client_id'],
            "redirect_uri": redirect, "scope": ' '.join(oauth['scopes']), "state": state,
            "code_challenge": challenge, "code_challenge_method": "S256"}))
        deadline = time.monotonic() + 180
        while not response and time.monotonic() < deadline:
            server.handle_request()
    if not response:
        raise AccessError("oauth_timeout", "No se recibió autorización. Volvé a intentarlo; el proveedor debe admitir redirección loopback de escritorio.")
    return _token(profile, {"grant_type": "authorization_code", "client_id": oauth['client_id'],
        "code": response['code'], "code_verifier": verifier, "redirect_uri": redirect})


def refresh_if_needed(profile, credentials, save):
    if time.time() < float(credentials.get('expires_at', 0)):
        return credentials
    if not credentials.get('refresh_token'):
        raise AccessError("authorization_expired", "La autorización venció. Abrí el asistente y autorizá otra vez.")
    refreshed = _token(profile, {"grant_type": "refresh_token", "client_id": profile['oauth']['client_id'],
                                "refresh_token": credentials['refresh_token']})
    refreshed['refresh_token'] = refreshed.get('refresh_token') or credentials['refresh_token']
    if save is None:
        raise AccessError("credential_store_required", "Guardá la autorización protegida antes de sincronizar en segundo plano.")
    save(refreshed)
    return refreshed
