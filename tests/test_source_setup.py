import json
from decimal import Decimal
from pathlib import Path

import pytest

from aiva_collector.config import load_config
from aiva_collector.errors import ConfigError, ValidationError
from aiva_collector.source_setup import preview_source, save_source_preview, validate_profile, reprocess_rejected
from test_collector_deduplication import _config, _mock_backend

MAPPING = {key: key for key in ["fecha", "producto_codigo", "producto_nombre", "cantidad_vendida", "precio_venta", "descuento", "costo_unitario"]}


@pytest.fixture
def setup_source(tmp_path, monkeypatch):
    config_path = _config(tmp_path, move_processed=False)
    config = json.loads(config_path.read_text())
    config.update(source_read_only=True, move_error_files=False)
    config_path.write_text(json.dumps(config))
    monkeypatch.setenv("AIVA_COLLECTOR_STANDARD_CONFIG", str(config_path))
    monkeypatch.setenv("AIVA_COLLECTOR_DATA_DIR", str(tmp_path / "programdata"))
    monkeypatch.setattr("aiva_collector.cli.CollectorClient.post_mapping_candidate", lambda *args: {})
    source = tmp_path / "input" / "sales.csv"
    def write(discount="10", price="100", quantity="2"):
        source.write_text(",".join(MAPPING) + f"\n2026-09-01,A,Producto sintético,{quantity},{price},{discount},40\n", encoding="utf-8-sig")
    write()
    return config_path, source, write


@pytest.mark.parametrize("price,kind,discount,expected_net,expected_discount", [
    ("gross_before_discount", "per_unit", "10", "180", "20"),
    ("gross_before_discount", "per_line", "10", "190", "10"),
    ("gross_before_discount", "percentage", "10", "180", "20"),
    ("final_net", "per_unit", "10", "200", "20"),
    ("final_net", "per_line", "10", "200", "10"),
    ("final_net", "percentage", "20", "200", "50"),
    ("gross_before_discount", "percentage", "100", "0", "200"),
])
def test_preview_independent_discount_math(setup_source, price, kind, discount, expected_net, expected_discount):
    _config_path, source, write = setup_source
    write(discount)
    before = source.read_bytes()
    result = preview_source(source, MAPPING, price=price, discount=kind, complete=True)
    totals = result["totals"]
    assert Decimal(totals["ventas_netas"]) == Decimal(expected_net)
    assert Decimal(totals["descuentos"]) == Decimal(expected_discount)
    assert Decimal(totals["costos"]) == 80
    assert Decimal(totals["margen"]) == Decimal(expected_net) - 80
    assert result["summary"]["resumen_financiero"]["facturacion_total"] == float(expected_net)
    assert result["summary"]["daily_snapshot"]["price_semantics"] == "final_net_with_discounts"
    assert source.read_bytes() == before


@pytest.mark.parametrize("discount,price,kind", [("abc", "final_net", "per_line"), ("-1", "final_net", "per_line"), ("201", "gross_before_discount", "per_line"), ("100", "final_net", "percentage"), ("101", "gross_before_discount", "percentage")])
def test_bad_discounts_never_become_zero(setup_source, discount, price, kind):
    _, source, write = setup_source
    write(discount)
    with pytest.raises((ValueError, ValidationError)):
        preview_source(source, MAPPING, price=price, discount=kind)


def test_save_preview_change_guard_and_context(setup_source):
    config_path, source, write = setup_source
    result = preview_source(source, MAPPING, price="final_net", discount="per_line")
    write("11")
    with pytest.raises(ConfigError, match="cambió"):
        save_source_preview(result)
    result = preview_source(source, MAPPING, price="final_net", discount="per_line")
    assert save_source_preview(result).ok
    config = load_config(config_path)
    validate_profile(config)
    assert config.raw["daily_snapshot_complete"] is False
    config.raw["commerce_id"] = "other"
    with pytest.raises(ConfigError, match="vinculación"):
        validate_profile(config)


def test_rejection_is_not_repeated_and_selective_recovery_is_idempotent(setup_source, monkeypatch):
    from aiva_collector.cli import main
    from aiva_collector.local_state import connect, local_db_path
    config_path, source, _ = setup_source
    sent = []
    _mock_backend(monkeypatch, sent)
    assert main(["run-auto", "--config", str(config_path)]) == 2
    with connect(local_db_path(load_config(config_path))) as conn:
        first_events = conn.execute("SELECT count(*) FROM processed_file_events WHERE event_type='processing_error'").fetchone()[0]
    assert main(["run-auto", "--config", str(config_path)]) == 2
    with connect(local_db_path(load_config(config_path))) as conn:
        assert conn.execute("SELECT count(*) FROM processed_file_events WHERE event_type='processing_error'").fetchone()[0] == first_events
    assert not sent
    result = preview_source(source, MAPPING, price="gross_before_discount", discount="per_unit", complete=True)
    save_source_preview(result)
    assert reprocess_rejected(source).ok
    assert len(sent) == 1
    assert Decimal(sent[0]["daily_snapshot"]["metrics"][0]["net_revenue"]) == 180
    assert main(["run-auto", "--config", str(config_path)]) == 0
    assert len(sent) == 1
    with pytest.raises(ConfigError, match="no está rechazado"):
        reprocess_rejected(source)
    assert source.exists()


def test_invalid_file_does_not_block_valid_file_and_headers_do_not_fallback(setup_source, monkeypatch):
    from aiva_collector.cli import main
    config_path, source, _ = setup_source
    result = preview_source(source, MAPPING, price="gross_before_discount", discount="per_line", complete=True)
    save_source_preview(result)
    (source.parent / "0-bad.csv").write_text("Wrong,Columns\n1,2\n")
    sent = []
    _mock_backend(monkeypatch, sent)
    assert main(["run-auto", "--config", str(config_path)]) == 2
    assert len(sent) == 1
    assert Decimal(sent[0]["daily_snapshot"]["metrics"][0]["net_revenue"]) == 190


def test_new_activation_preserves_old_state_and_resets_source(setup_source, monkeypatch):
    from aiva_collector.cli import _write_activation_config
    config_path, source, _ = setup_source
    save_source_preview(preview_source(source, MAPPING, price="final_net", discount="per_line", complete=True))
    old = load_config(config_path)
    old.path("state_dir").mkdir(exist_ok=True)
    marker = old.path("state_dir") / "history-marker"
    marker.write_text("preserved")
    _write_activation_config(config_path, backend_url=old.backend_url, response={"commerce_id": "new", "collector_id": "new-collector", "config_defaults": old.raw})
    new = load_config(config_path)
    assert new.raw["source_setup_required"] is True
    assert not new.column_mapping and "daily_snapshot_complete" not in new.raw
    assert new.path("state_dir") != old.path("state_dir")
    assert marker.read_text() == "preserved"
    assert source.exists()


def test_queue_other_tenant_is_untouched(tmp_path):
    from test_offline_queue import _config as queue_config, _payload, _insert_file, Client
    from aiva_collector.local_state import connect
    from aiva_collector.offline_queue import enqueue_payload, process_queue
    config = queue_config(tmp_path)
    conn = connect(tmp_path / "state.db")
    _insert_file(conn, tmp_path)
    enqueue_payload(conn, config, file_id="file-1", payload=_payload())
    before = tuple(conn.execute("SELECT * FROM upload_queue").fetchone())
    config.raw["commerce_id"] = "other"
    client = Client([])
    result = process_queue(conn, config, client=client, force=True)
    assert result.skipped == 1 and not client.sent
    assert tuple(conn.execute("SELECT * FROM upload_queue").fetchone()) == before
    conn.close()


def test_explicit_xlsx_sheet_header_stock_date(setup_source):
    from openpyxl import Workbook
    _, csv_source, _ = setup_source
    source = csv_source.with_suffix(".xlsx")
    book = Workbook()
    sheet = book.active
    sheet.title = "Ventas"
    sheet.append(["Reporte sintético"])
    mapping = {**MAPPING, "stock_actual": "Stock", "fecha_stock": "Fecha stock"}
    sheet.append(list(mapping.values()))
    sheet.append(["2026-09-01", "A", "Producto", 2, 100, 10, 40, 8, "2026-08-31"])
    book.save(source)
    preview = preview_source(source, mapping, price="final_net", discount="per_line", sheet="Ventas", header_row=2)
    assert preview["summary"]["daily_snapshot"]["metrics"][0]["closing_stock"] is None
    with pytest.raises(ValidationError, match="hoja"):
        preview_source(source, mapping, price="final_net", discount="per_line", sheet="Missing")


def test_same_bytes_in_another_source_have_independent_history(setup_source, monkeypatch, tmp_path):
    from aiva_collector.cli import main
    from aiva_collector.local_state import connect, local_db_path
    config_path, source, _ = setup_source
    sent = []
    _mock_backend(monkeypatch, sent)
    save_source_preview(preview_source(source, MAPPING, price="final_net", discount="per_line"))
    assert main(["run-auto", "--config", str(config_path)]) == 0
    other_folder = tmp_path / "other-source"
    other_folder.mkdir()
    other = other_folder / source.name
    other.write_bytes(source.read_bytes())
    save_source_preview(preview_source(other, MAPPING, price="final_net", discount="per_line"))
    assert main(["run-auto", "--config", str(config_path)]) == 0
    assert len(sent) == 2
    assert sent[0]["daily_snapshot"]["source_id"] != sent[1]["daily_snapshot"]["source_id"]
    with connect(local_db_path(load_config(config_path))) as conn:
        assert conn.execute("SELECT count(*) FROM processed_files WHERE status='sent'").fetchone()[0] == 2


def test_rc7_sqlite_upgrade_backup_restores_and_retains_rows(tmp_path):
    import sqlite3
    from aiva_collector.local_state import connect, upsert_detected_file
    source = tmp_path / "synthetic.csv"
    source.write_text("synthetic")
    database = tmp_path / "state.db"
    conn = connect(database)
    upsert_detected_file(conn, file_id="prior", commerce_id="tenant", collector_id="collector", path=source, file_sha256="old", status="sent")
    conn.execute("DROP INDEX idx_processed_files_context_source_sha256_schema")
    conn.execute("ALTER TABLE processed_files DROP COLUMN source_id")
    conn.execute("CREATE UNIQUE INDEX idx_processed_files_context_sha256_schema ON processed_files(file_sha256)")
    conn.commit()
    conn.close()
    conn = connect(database)
    assert conn.execute("SELECT status FROM processed_files WHERE file_id='prior'").fetchone()[0] == "sent"
    conn.close()
    backups = list(tmp_path.glob("aiva_collector.pre-rc8-*.db"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as backup, sqlite3.connect(tmp_path / "restore.db") as restored:
        backup.backup(restored)
        assert restored.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert restored.execute("SELECT file_id,status FROM processed_files").fetchone() == ("prior", "sent")
    conn = connect(database)
    conn.close()
    assert len(list(tmp_path.glob("aiva_collector.pre-rc8-*.db"))) == 1
