"""Explicit registry: driver detection never implies schema compatibility."""
from .base import AccessError

REGISTRY = {
    "files": {"implemented": True, "integration": "csv_xlsx", "requires": "exportación tabular"},
    "rest": {"implemented": True, "integration": "synthetic_http_server", "requires": "perfil documentado del proveedor"},
    "sqlite": {"implemented": True, "integration": "real_sqlite", "requires": "tabla autorizada y fechas ISO"},
    "odbc": {"implemented": True, "integration": "external_test_required", "requires": "SQL Server, controlador x64 y cuenta de lectura"},
    "postgresql": {"implemented": False, "requires": "adaptación y pruebas del motor/perfil"},
    "mysql_mariadb": {"implemented": False, "requires": "adaptación y pruebas del motor/perfil"},
    "firebird": {"implemented": False, "requires": "adaptación y pruebas del motor/perfil"},
    "access": {"implemented": False, "requires": "adaptación, controlador compatible y pruebas"},
}


def create_connector(profile, secrets=None, **kwargs):
    kind = profile.get("kind")
    if kind == "files":
        from .files import FilesConnector
        return FilesConnector(profile, secrets)
    if kind == "rest":
        from .rest import RESTConnector
        return RESTConnector(profile, secrets, **kwargs)
    if kind == "sqlite":
        from .sqlite import SQLiteConnector
        return SQLiteConnector(profile, secrets)
    if kind == "odbc":
        from .odbc import SQLServerConnector
        return SQLServerConnector(profile, secrets)
    raise AccessError("profile_required", "Este motor necesita un conector y perfil verificados. Pedí CSV/XLSX como alternativa.")
