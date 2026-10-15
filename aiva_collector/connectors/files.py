from pathlib import Path

from .base import AccessError, Connector, Reading, bounded_rows, business_date
from ..config import CollectorConfig
from ..normalizer import parse_date
from ..readers import discover_input_files, read_file


class FilesConnector(Connector):
    def read(self, window, *, sample=False):
        p = self.profile
        cfg = CollectorConfig({**p.get("reader", {}), "input_dir": p["folder"], "column_mapping": p["mapping"], "max_input_rows": self.max_rows}, Path("unused"))
        files = discover_input_files(cfg)
        if len(files) > 200:
            raise AccessError("file_limit", "Hay demasiados archivos. Prepará una carpeta de exportaciones acotada.")
        selected, outside, days = [], 0, {}
        for path in files:
            if p.get("suffix") and path.suffix.lower() != p["suffix"]:
                continue
            if path.stat().st_size > min(int(p.get("max_file_bytes", 50000000)), 100000000):
                raise AccessError("file_limit", "El archivo supera el tamaño permitido. Pedí exportaciones por períodos menores.")
            from ..file_fingerprint import compute_file_sha256
            digest = compute_file_sha256(path)
            raw = bounded_rows(read_file(path, cfg), self.max_rows)
            found = set()
            for row in raw:
                day = business_date(row.get(p["mapping"].get("fecha")), p.get("timezone", "America/Argentina/Buenos_Aires"))
                if day is None:
                    # Keep malformed rows for explicit rejection; never silently certify a file.
                    selected.append(row)
                elif window.start <= day <= window.end:
                    selected.append(row)
                    found.add(day)
                else:
                    outside += 1
            for day in found:
                if day in days:
                    raise AccessError("overlapping_files", "Dos archivos cubren el mismo día. Elegí un único snapshot completo; no se suman lotes.")
                days[day] = path
            if compute_file_sha256(path) != digest:
                raise AccessError("source_changed", "El archivo cambió durante la lectura. Se reintentará sin avanzar.")
        return Reading(bounded_rows(selected, self.max_rows), outside=outside, complete=p.get("complete_days") is True)
