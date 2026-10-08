from __future__ import annotations

import base64
import ctypes
import os
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path

from .errors import ConfigError


TOKEN_FILE_NAME = "collector.token"


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def token_path(state_dir: Path) -> Path:
    return state_dir / TOKEN_FILE_NAME


def save_token(state_dir: Path, token: str) -> Path:
    state_dir.mkdir(parents=True, exist_ok=True)
    path = token_path(state_dir)
    if sys.platform.startswith("win"):
        payload = _dpapi_protect(token.encode("utf-8"))
        path.write_bytes(b"DPAPI:" + base64.b64encode(payload))
    else:
        path.write_text("PLAINTEXT-FALLBACK:" + token, encoding="utf-8")
        os.chmod(path, 0o600)
    _restrict_file_to_current_user(path)
    return path


def load_token(state_dir: Path) -> str | None:
    path = token_path(state_dir)
    if not path.exists():
        return None
    raw = path.read_bytes()
    if raw.startswith(b"DPAPI:"):
        if not sys.platform.startswith("win"):
            raise ConfigError("collector_not_activated: token DPAPI solo puede leerse en Windows")
        encrypted = base64.b64decode(raw.removeprefix(b"DPAPI:"))
        return _dpapi_unprotect(encrypted).decode("utf-8")
    text = raw.decode("utf-8")
    if text.startswith("PLAINTEXT-FALLBACK:"):
        return text.removeprefix("PLAINTEXT-FALLBACK:")
    raise ConfigError("collector_not_activated: formato de token local invalido")


TOKEN_MISSING = "missing"
TOKEN_READABLE = "readable"
TOKEN_OTHER_USER = "other_user"
TOKEN_UNREADABLE = "unreadable"


def token_status(state_dir: Path) -> str:
    """Dice si esta sesion de Windows puede usar el token guardado.

    El token queda cifrado con DPAPI para el usuario que activo AIVA y el
    archivo solo es legible para el. Si en la PC inicia sesion otra persona, la
    tarea automatica corre con esa otra cuenta: el archivo existe pero no se
    puede leer ni descifrar. Eso no es un error del comercio y no debe pisar el
    estado de la sincronizacion del usuario que si activo.
    """

    path = token_path(state_dir)
    try:
        if not path.exists():
            return TOKEN_MISSING
    except PermissionError:
        return TOKEN_OTHER_USER
    try:
        token = load_token(state_dir)
    except PermissionError:
        # El archivo esta restringido a la cuenta que activo (icacls).
        return TOKEN_OTHER_USER
    except (OSError, ConfigError):
        # Token corrupto, o DPAPI no lo descifra (clave cambiada, otra PC):
        # no es "otro usuario". Se informa como falta de activacion.
        return TOKEN_UNREADABLE
    return TOKEN_READABLE if token else TOKEN_MISSING


def _dpapi_protect(data: bytes) -> bytes:
    blob_in = _blob_from_bytes(data)
    blob_out = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(blob_in),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(blob_out),
    ):
        raise ConfigError("No se pudo proteger token con Windows DPAPI")
    return _bytes_from_blob(blob_out)


def _dpapi_unprotect(data: bytes) -> bytes:
    blob_in = _blob_from_bytes(data)
    blob_out = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(blob_out),
    ):
        raise ConfigError("No se pudo leer token protegido con Windows DPAPI")
    return _bytes_from_blob(blob_out)


def _blob_from_bytes(data: bytes) -> DATA_BLOB:
    buffer = ctypes.create_string_buffer(data)
    return DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))


def _bytes_from_blob(blob: DATA_BLOB) -> bytes:
    try:
        return ctypes.string_at(blob.pbData, blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob.pbData)


def _restrict_file_to_current_user(path: Path) -> None:
    if not sys.platform.startswith("win"):
        return
    try:
        user = os.getlogin()
        subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:R,W"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        pass
