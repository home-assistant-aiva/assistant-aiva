"""Source secrets use Windows user DPAPI, same identity as the background task.

There is deliberately no plaintext fallback for integration credentials.
"""
import base64
import json
import sys
import csv
import io
import subprocess
import os
import uuid

from .connection_config import atomic_json, context, digest
from .connectors.base import AccessError
from .token_store import _dpapi_protect, _dpapi_unprotect


class CredentialVault:
    def __init__(self, config, source_id):
        self.binding = digest([context(config), source_id])
        self.path = config.path("state_dir") / "credentials" / (self.binding + ".dpapi")

    def store(self, secrets):
        if not sys.platform.startswith('win'):
            raise AccessError("windows_required", "El guardado de credenciales requiere Windows DPAPI; no se guardarán en texto plano.")
        payload = json.dumps({"binding": self.binding, "values": secrets}).encode()
        encrypted = base64.b64encode(_dpapi_protect(payload)).decode()
        candidate = self.path.with_name(self.path.name + "." + uuid.uuid4().hex + ".candidate")
        atomic_json(candidate, {"protected": encrypted})
        try:
            identity = subprocess.run(['whoami', '/user', '/fo', 'csv', '/nh'], capture_output=True, text=True, check=True, timeout=5)
            sid = next(csv.reader(io.StringIO(identity.stdout)))[1].strip()
            if not sid.startswith('S-1-'):
                raise ValueError
            result = subprocess.run(['icacls', str(candidate), '/inheritance:r', '/grant:r', f'*{sid}:F'],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            if result.returncode:
                raise ValueError
        except Exception:
            candidate.unlink(missing_ok=True)
            raise AccessError('credential_acl_failed', 'Windows no pudo restringir las credenciales a esta identidad. Revisá permisos de ProgramData.') from None
        os.replace(candidate, self.path)

    def load(self):
        if not self.path.exists():
            return {}
        if not sys.platform.startswith('win'):
            raise AccessError("windows_required", "Las credenciales protegidas sólo se pueden abrir desde su usuario de Windows.")
        try:
            payload = json.loads(_dpapi_unprotect(base64.b64decode(json.loads(self.path.read_text())["protected"])))
            if payload["binding"] != self.binding:
                raise ValueError
            return payload["values"]
        except Exception:
            raise AccessError("credentials_unreadable", "Usá la sesión de Windows que configuró AIVA o reemplazá las credenciales.") from None

    def delete(self):
        self.path.unlink(missing_ok=True)
