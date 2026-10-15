import sqlite3
import time
from pathlib import Path

from .base import AccessError, Connector, Reading, bounded_rows, identifier


class SQLiteConnector(Connector):
    def read(self, window, *, sample=False):
        p = self.profile
        table = identifier(p["table"])
        columns = [identifier(x) for x in p["columns"]]
        date_column = identifier(p["date_column"])
        if date_column not in columns:
            raise AccessError("date_column_missing", "Incluí la fecha comercial entre las columnas del perfil.")
        path = Path(p["path"]).resolve(strict=True)
        # mode=ro preserves WAL semantics. Never use immutable=1 on a live database.
        conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=self.timeout)
        try:
            if hasattr(conn, "setlimit"):
                conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 1000000)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only=ON")
            conn.enable_load_extension(False)
            # Only ordinary configured tables. Views, virtual tables and SQL supplied
            # by a provider may execute functions; they are deliberately unsupported.
            row = conn.execute("SELECT sql FROM sqlite_schema WHERE type='table' AND name=?", (table,)).fetchone()
            if not row or not row[0].lstrip().upper().startswith("CREATE TABLE"):
                raise AccessError("table_unsupported", "Seleccioná una tabla ordinaria autorizada; vistas y tablas virtuales requieren exportación.")
            started = time.monotonic()
            conn.set_progress_handler(lambda: int(time.monotonic() - started > self.timeout), 1000)
            def authorize(action, arg1, arg2, db, trigger):
                if action == sqlite3.SQLITE_SELECT:
                    return sqlite3.SQLITE_OK
                if action == sqlite3.SQLITE_READ and arg1 == table and arg2 in columns and db == "main" and trigger is None:
                    return sqlite3.SQLITE_OK
                return sqlite3.SQLITE_DENY
            conn.set_authorizer(authorize)
            quoted = ','.join('"' + x + '"' for x in columns)
            # The profile requires ISO dates/timestamps in this column.
            limit = min(self.max_rows, 100) if sample else self.max_rows
            from datetime import timedelta
            query = f'SELECT {quoted} FROM "{table}" WHERE "{date_column}" >= ? AND "{date_column}" < ? LIMIT ?'
            rows = bounded_rows(conn.execute(query, (window.start.isoformat(), (window.end + timedelta(days=1)).isoformat(), (limit if sample else limit + 1))), limit)
            return Reading(rows, complete=p.get("complete_days") is True,
                           empty_confirmed=p.get("empty_days_complete") is True)
        except sqlite3.Error:
            raise AccessError("sqlite_read_failed", "No se pudo leer de forma segura. Revisá permisos, esquema, bloqueo y archivos WAL/SHM; pedí una exportación consistente si persiste.") from None
        finally:
            conn.close()
