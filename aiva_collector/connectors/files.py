"""Read-only bounded exports with explicit, durable replacement order."""

from datetime import timedelta
from pathlib import Path

from .base import AccessError, Connector, Reading, bounded_rows, business_date
from ..config import CollectorConfig
from ..file_fingerprint import compute_file_sha256
from ..readers import discover_input_files, read_file


class FilesConnector(Connector):
    def read(self, window, *, sample=False):
        p = self.profile
        cfg = CollectorConfig({**p.get("reader", {}), "input_dir":p["folder"],
            "column_mapping":p["mapping"],"max_input_rows":self.max_rows}, Path("unused"))
        files = [path for path in discover_input_files(cfg)
                 if not p.get("suffix") or path.suffix.lower()==p["suffix"]]
        if len(files)>200:
            raise AccessError("file_limit", "Hay demasiados archivos. Prepará una carpeta de exportaciones acotada.")
        cache = getattr(self,"_raw_cache",{})
        candidates = []
        invalid = []
        total_rows = 0
        seen_hashes = set()
        for path in files:
            if path.stat().st_size > min(int(p.get("max_file_bytes",50000000)),100000000):
                raise AccessError("file_limit", "El archivo supera el tamaño permitido. Dividí por días completos.")
            stamp=(path.stat().st_size,path.stat().st_mtime_ns)
            saved=cache.get(path)
            if saved and saved[0]==stamp:
                raw,digest,declared=saved[1:]
            else:
                digest=compute_file_sha256(path)
                raw=bounded_rows(read_file(path,cfg),self.max_rows)
                if compute_file_sha256(path)!=digest:
                    raise AccessError("source_changed","El archivo cambió durante la lectura; se reintentará.")
                declared=self._period(raw,p)
                cache[path]=(stamp,raw,digest,declared)
            if digest in seen_hashes:
                continue
            seen_hashes.add(digest)
            total_rows+=len(raw)
            by_day={}
            for row in raw:
                day=business_date(row.get(p["mapping"].get("fecha")),p.get("timezone","America/Argentina/Buenos_Aires"))
                if day is None:
                    invalid.append(row)
                elif window.start<=day<=window.end:
                    by_day.setdefault(day,[]).append(row)
            candidates.append({"path":path,"hash":digest,"period":declared,"rows":by_day})
        self._raw_cache=cache
        selected=list(invalid)
        chosen_hash=None
        empty_confirmed=False
        for offset in range((window.end-window.start).days+1):
            day=window.start+timedelta(days=offset)
            covered=[item for item in candidates if day in item["rows"] or
                     (item["period"] and item["period"][0]<=day<=item["period"][1])]
            if not covered:
                continue
            if len(covered)>1:
                versions=p.get("_file_versions") or {}
                if not p.get("complete_days") or any(not item["period"] for item in covered) or any(item["hash"] not in versions for item in covered):
                    raise AccessError("overlapping_files","Dos archivos cubren el mismo día sin orden y cobertura acreditados. Revisalos; no se suman.")
                ordered=sorted(covered,key=lambda item:versions[item["hash"]])
                newest=ordered[-1]
                if (versions[newest["hash"]]==versions[ordered[-2]["hash"]] or
                    len(newest["rows"].get(day,[]))<max(len(item["rows"].get(day,[])) for item in ordered[:-1])):
                    raise AccessError("overlapping_files","Una exportación posterior puede ser parcial o simultánea. Revisá el día antes de reemplazarlo.")
                chosen=newest
            else:
                chosen=covered[0]
            selected.extend(chosen["rows"].get(day,[]))
            if chosen["period"] and chosen["period"][0]<=day<=chosen["period"][1] and p.get("complete_days"):
                empty_confirmed=True
            chosen_hash=chosen["hash"] if chosen_hash in (None,chosen["hash"]) else None
        if any(compute_file_sha256(item["path"])!=item["hash"] for item in candidates):
            raise AccessError("source_changed","Una exportación cambió durante la lectura; se reintentará.")
        return Reading(bounded_rows(selected,self.max_rows),outside=max(0,total_rows-len(selected)),
                       complete=p.get("complete_days") is True,empty_confirmed=empty_confirmed,
                       source_file_sha256=chosen_hash)

    def validate_overlaps(self, start, end):
        """Reject ambiguous replacements before sending any inventory from new files."""
        for offset in range((end-start).days+1):
            day=start+timedelta(days=offset)
            self.read(type("DayWindow", (), {"start":day,"end":day})())

    @staticmethod
    def _period(rows,p):
        start=p["mapping"].get("periodo_desde")
        end=p["mapping"].get("periodo_hasta")
        if not (start and end) or not rows:
            return None
        dates={(business_date(row.get(start),p.get("timezone","America/Argentina/Buenos_Aires")),
                business_date(row.get(end),p.get("timezone","America/Argentina/Buenos_Aires"))) for row in rows}
        if len(dates)!=1:
            raise AccessError("export_period_invalid","El rango de exportación cambia entre filas. Revisá el archivo.")
        low,high=next(iter(dates))
        if low is None or high is None or high<low:
            raise AccessError("export_period_invalid","El rango de exportación es ilegible. Revisá el archivo.")
        for row in rows:
            day=business_date(row.get(p["mapping"].get("fecha")),p.get("timezone","America/Argentina/Buenos_Aires"))
            if day is not None and not low<=day<=high:
                raise AccessError("export_period_invalid","Hay ventas fuera del rango declarado por la exportación.")
        return low,high
