"""Synthetic persistence fixture, only for a disposable GitHub Windows runner."""
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aiva_collector.config import load_config
from aiva_collector.local_state import connect, local_db_path, upsert_detected_file, update_file_state
from aiva_collector.token_store import save_token, load_token
from aiva_collector.offline_queue import enqueue_payload

if os.environ.get("GITHUB_ACTIONS") != "true":
    raise SystemExit("Only a disposable GitHub Actions runner is supported")
config = load_config(Path(os.environ["ProgramData"]) / "AIVA/Collector/config.windows.json")
if config.commerce_id != "commerce-simulated-rc1":
    raise SystemExit("Not the expected synthetic upgrade fixture")
source = config.path("input_dir") / "ventas-sinteticas.csv"
conn = connect(local_db_path(config))
upsert_detected_file(conn, file_id="synthetic-upgrade-pending", commerce_id=config.commerce_id, collector_id=config.collector_id, backend_url=config.backend_url, path=source, file_sha256="0"*64)
update_file_state(conn, "synthetic-upgrade-pending", status="pending_send")
enqueue_payload(conn, config, file_id="synthetic-upgrade-pending", payload={"commerce_id": config.commerce_id, "collector_id": config.collector_id, "fecha_inicio": "2026-09-01", "fecha_fin": "2026-09-01", "productos_resumidos": []})
# Reproduce the RC7 schema so the new binary must perform its additive migration.
conn.execute("DROP INDEX idx_processed_files_context_source_sha256_schema")
conn.execute("ALTER TABLE processed_files DROP COLUMN source_id")
conn.execute("CREATE UNIQUE INDEX idx_processed_files_context_sha256_schema ON processed_files(COALESCE(commerce_id, ''),COALESCE(collector_id, ''),COALESCE(backend_url, ''),file_sha256,COALESCE(source_schema_version, '1.0.0'))")
conn.commit()
assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
conn.close()
save_token(config.path("state_dir"), "SIMULATED-RC1-TOKEN")
assert load_token(config.path("state_dir")) == "SIMULATED-RC1-TOKEN"
print("Synthetic SQLite history, pending queue and DPAPI token prepared")
