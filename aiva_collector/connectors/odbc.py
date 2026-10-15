"""SQL Server ODBC reader: generated queries, restricted objects and effective permissions."""
from datetime import datetime, time, timedelta

from .base import AccessError, Connector, Reading, bounded_rows, identifier

DRIVER_HELP = "Instalá Microsoft ODBC Driver 18 for SQL Server de la arquitectura del Collector (x64): https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server"


def odbc_module():
    try:
        import pyodbc
        return pyodbc
    except ImportError:
        raise AccessError("driver_required", DRIVER_HELP) from None


def escape(value):
    text = str(value)
    if any(c in text for c in '\r\n\x00'):
        raise AccessError("connection_invalid", "Revisá los parámetros de conexión.")
    return '{' + text.replace('}', '}}') + '}'


class SQLServerConnector(Connector):
    def availability(self):
        driver = self.profile.get("driver", "ODBC Driver 18 for SQL Server")
        if driver not in odbc_module().drivers():
            raise AccessError("driver_required", DRIVER_HELP)
        return {"state": "configuration_incomplete", "message": "Controlador disponible; faltan probar acceso y perfil de tablas."}

    def _connect(self):
        self.availability()
        p = self.profile
        if p.get("engine") != "sqlserver":
            raise AccessError("profile_required", "Este lector sólo verifica SQL Server; otros motores requieren adaptación de perfil.")
        parts = ["DRIVER=" + escape(p.get("driver", "ODBC Driver 18 for SQL Server")),
                 "SERVER=" + escape(p["server"]), "DATABASE=" + escape(p["database"]),
                 "Encrypt=yes", "TrustServerCertificate=no", "ApplicationIntent=ReadOnly"]
        if p.get("auth") == "windows_integrated":
            parts.append("Trusted_Connection=yes")
        elif p.get("auth") == "database_password":
            if not self.secrets.get("username") or not self.secrets.get("password"):
                raise AccessError("credentials_required", "Pedí una cuenta de base de datos con SELECT sobre los objetos autorizados.")
            parts.extend(["UID=" + escape(self.secrets["username"]), "PWD=" + escape(self.secrets["password"])])
        else:
            raise AccessError("auth_unsupported", "Elegí cuenta de base de datos o autenticación integrada de Windows.")
        try:
            conn = odbc_module().connect(';'.join(parts), timeout=self.timeout, readonly=True, autocommit=False)
            conn.timeout = self.timeout
            return conn
        except Exception as exc:
            state = str(exc.args[0]) if getattr(exc, "args", None) else ""
            if state.startswith("28"):
                raise AccessError("credentials_invalid", "La base rechazó las credenciales.") from None
            raise AccessError("database_unreachable", "No se pudo abrir la base. Revisá servidor, certificado, red y permisos.") from None

    def read(self, window, *, sample=False):
        p = self.profile
        table, schema = identifier(p["table"]), identifier(p.get("schema", "dbo"))
        columns = [identifier(c) for c in p["columns"]]
        day = identifier(p["date_column"])
        if day not in columns:
            raise AccessError("date_column_missing", "Incluí la columna de fecha entre las columnas autorizadas.")
        obj = schema + '.' + table
        conn = self._connect()
        cursor = None
        try:
            cursor = conn.cursor()
            # ApplicationIntent is routing, not a permissions boundary. Reject broad
            # permissions and any executable/writable object before reading data.
            cursor.execute("SELECT permission_name FROM sys.fn_my_permissions(NULL, 'SERVER')")
            if any(str(r[0]).upper() not in {"CONNECT SQL", "VIEW ANY DATABASE", "VIEW ANY DEFINITION"} for r in cursor):
                raise AccessError("read_only_required", "La cuenta tiene permisos de servidor excesivos; pedí una cuenta específica de lectura.")
            cursor.execute("SELECT permission_name FROM sys.fn_my_permissions(NULL, 'DATABASE')")
            if any(str(r[0]).upper() not in {"CONNECT", "SELECT", "VIEW DEFINITION"} for r in cursor):
                raise AccessError("read_only_required", "La cuenta tiene permisos de escritura o ejecución; pedí una cuenta específica de lectura.")
            cursor.execute("SELECT permission_name FROM sys.fn_my_permissions(?, 'OBJECT')", obj)
            permissions = {str(r[0]).upper() for r in cursor}
            if "SELECT" not in permissions or permissions - {"SELECT", "VIEW DEFINITION"}:
                raise AccessError("read_only_required", "Se requiere SELECT sin escritura ni ejecución sobre la tabla elegida.")
            cursor.execute("SELECT t.name FROM sys.tables t JOIN sys.schemas s ON s.schema_id=t.schema_id WHERE s.name=? AND t.name=? AND t.is_ms_shipped=0", schema, table)
            if cursor.fetchone() is None:
                raise AccessError("table_unsupported", "Usá una tabla ordinaria autorizada. Vistas y procedimientos requieren un perfil revisado.")
            cursor.execute("SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=? AND TABLE_NAME=?", schema, table)
            definitions = {str(r[0]): (str(r[1]).lower(), r[2]) for r in cursor}
            for column in columns:
                definition = definitions.get(column)
                if definition is None or definition[0] in {'image','binary','varbinary','xml','text','ntext','sql_variant','geography','geometry'} or (definition[1] is not None and (definition[1] < 0 or definition[1] > 4096)):
                    raise AccessError("column_unsupported", "El perfil contiene campos extensos, binarios o no verificados; pedí una exportación tabular acotada.")
            limit = min(100, self.max_rows) if sample else self.max_rows
            projection = ','.join('[' + c + ']' for c in columns)
            query = f"SELECT TOP {limit if sample else limit + 1} {projection} FROM [{schema}].[{table}] WHERE [{day}] >= ? AND [{day}] < ? ORDER BY [{day}]"
            cursor.execute(query, datetime.combine(window.start, time.min), datetime.combine(window.end + timedelta(days=1), time.min))
            names = [c[0] for c in cursor.description]
            rows = bounded_rows((dict(zip(names, r)) for r in cursor), limit)
            return Reading(rows, complete=p.get("complete_days") is True, empty_confirmed=p.get("empty_days_complete") is True)
        except AccessError:
            raise
        except Exception:
            raise AccessError("database_read_failed", "La consulta no pudo completarse. Revisá permisos, columnas, fechas y límites del perfil.") from None
        finally:
            if cursor is not None:
                cursor.close()
            conn.rollback()
            conn.close()
