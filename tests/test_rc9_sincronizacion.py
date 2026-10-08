"""RC9: ningun archivo voltea la corrida y la tarea respeta al usuario de Windows."""
import json
from pathlib import Path

from aiva_collector.cli import main
from aiva_collector.config import load_config
from aiva_collector.local_state import connect, local_db_path
from aiva_collector.token_store import TOKEN_OTHER_USER
from test_collector_deduplication import _config, _mock_backend, _write_valid


def _state(config_path):
    path = Path(load_config(config_path).raw["state_dir"]) / "last_auto_run.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def test_archivo_bloqueado_por_otro_programa_no_corta_la_corrida(tmp_path, monkeypatch):
    config_path = _config(tmp_path)
    _write_valid(tmp_path / "input" / "a_bloqueado.csv", "Producto A")
    _write_valid(tmp_path / "input" / "b_libre.csv", "Producto B")
    sent = []
    _mock_backend(monkeypatch, sent)
    import aiva_collector.cli as cli
    real_hash = cli.compute_file_sha256

    def locked(path):
        if Path(path).name == "a_bloqueado.csv":
            raise PermissionError("El proceso no tiene acceso al archivo porque está siendo utilizado por otro proceso")
        return real_hash(path)

    monkeypatch.setattr(cli, "compute_file_sha256", locked)
    assert main(["run-auto", "--config", str(config_path)]) == 0
    assert len(sent) == 1 and sent[0]["productos_resumidos"][0]["producto_nombre"] == "Producto B"
    state = _state(config_path)
    assert state["files_skipped"] >= 1 and state["summaries_sent"] == 1


def test_falla_inesperada_en_un_archivo_no_frena_a_los_demas(tmp_path, monkeypatch):
    config_path = _config(tmp_path)
    _write_valid(tmp_path / "input" / "a_roto.csv", "Producto A")
    _write_valid(tmp_path / "input" / "b_sano.csv", "Producto B")
    sent = []
    _mock_backend(monkeypatch, sent)
    import aiva_collector.cli as cli
    real_build = cli.build_summary

    def boom(rows, *args, **kwargs):
        if rows and rows[0]["producto_nombre"] == "Producto A":
            raise RuntimeError("falla que nadie previo")
        return real_build(rows, *args, **kwargs)

    monkeypatch.setattr(cli, "build_summary", boom)
    monkeypatch.setattr(cli, "update_file_state", _crash_on_error_state(cli.update_file_state))
    assert main(["run-auto", "--config", str(config_path)]) == 2
    assert len(sent) == 1
    state = _state(config_path)
    assert state["result"] == "error" and "a_roto.csv" in state["error_summary"]
    with connect(local_db_path(load_config(config_path))) as conn:
        row = conn.execute("SELECT status, lease_expires_at FROM processed_files WHERE file_path LIKE '%a_roto.csv'").fetchone()
    # Queda listo para reintentar en la proxima corrida, no bloqueado 15 minutos.
    assert row["status"] in {"processing", "validated"} and row["lease_expires_at"] is None
    monkeypatch.setattr(cli, "build_summary", real_build)
    assert main(["run-auto", "--config", str(config_path)]) == 0
    assert len(sent) == 2


def _crash_on_error_state(original):
    """Simula que tambien falla el registro del error (base ocupada)."""

    def update(conn, file_id, **fields):
        if fields.get("status") == "error" and "nadie previo" in str(fields.get("error_message")):
            raise RuntimeError("database is locked")
        return original(conn, file_id, **fields)

    return update


def test_otro_usuario_de_windows_no_pisa_el_estado(tmp_path, monkeypatch, capsys):
    config_path = _config(tmp_path)
    _write_valid(tmp_path / "input" / "ventas.csv")
    monkeypatch.delenv("AIVA_COLLECTOR_TOKEN", raising=False)
    monkeypatch.setattr("aiva_collector.cli.token_status", lambda state_dir: TOKEN_OTHER_USER)
    # Tarea programada: termina en silencio.
    monkeypatch.setenv("AIVA_COLLECTOR_BACKGROUND", "1")
    assert main(["run-auto", "--config", str(config_path)]) == 0
    assert _state(config_path) is None
    # Desde la aplicacion: la persona tiene que ver por que no sincroniza.
    monkeypatch.delenv("AIVA_COLLECTOR_BACKGROUND")
    assert main(["run-auto", "--config", str(config_path)]) == 2
    assert "otro usuario de Windows" in capsys.readouterr().err
    assert _state(config_path) is None


def test_token_corrupto_no_se_confunde_con_otro_usuario(tmp_path):
    from aiva_collector.token_store import TOKEN_UNREADABLE, token_path, token_status
    state = tmp_path / "state"
    state.mkdir()
    token_path(state).write_bytes(b"basura")
    assert token_status(state) == TOKEN_UNREADABLE


def test_token_de_otra_cuenta_es_otro_usuario(tmp_path, monkeypatch):
    from aiva_collector import token_store
    state = tmp_path / "state"
    state.mkdir()
    token_store.token_path(state).write_bytes(b"DPAPI:xxx")

    def denied(state_dir):
        raise PermissionError("acceso denegado")

    monkeypatch.setattr(token_store, "load_token", denied)
    assert token_store.token_status(state) == token_store.TOKEN_OTHER_USER


def test_rechazo_del_backend_tras_reevaluar_no_se_repite(tmp_path, monkeypatch):
    """Si el Backend rechaza el archivo reevaluado, no se reenvia en cada corrida."""
    from aiva_collector.cli import _rejected_by_previous_version, VERSION
    from aiva_collector.local_state import add_event
    config = load_config(_config(tmp_path))
    with connect(local_db_path(config)) as conn:
        add_event(conn, file_id="f1", event_type="processing_error", level="error", message="x", context={"collector_version": "0.2.8rc8"})
        assert _rejected_by_previous_version(conn, "f1")
        add_event(conn, file_id="f1", event_type="rejected_file_reevaluated", level="info", message="x", context={"collector_version": VERSION})
        assert not _rejected_by_previous_version(conn, "f1")


def test_token_ilegible_no_rompe_la_configuracion(tmp_path, monkeypatch):
    config = load_config(_config(tmp_path))
    monkeypatch.delenv("AIVA_COLLECTOR_TOKEN", raising=False)

    def denied(state_dir):
        raise PermissionError("acceso denegado")

    monkeypatch.setattr("aiva_collector.config.load_token", denied)
    assert config.token is None


def test_archivo_rechazado_por_rc8_se_reevalua_una_vez(tmp_path, monkeypatch):
    from aiva_collector.source_setup import preview_source, save_source_preview
    config_path = _config(tmp_path, move_processed=False)
    raw = json.loads(config_path.read_text())
    raw.update(source_read_only=True, move_error_files=False)
    config_path.write_text(json.dumps(raw))
    monkeypatch.setenv("AIVA_COLLECTOR_STANDARD_CONFIG", str(config_path))
    monkeypatch.setenv("AIVA_COLLECTOR_DATA_DIR", str(tmp_path / "programdata"))
    monkeypatch.setattr("aiva_collector.cli.CollectorClient.post_mapping_candidate", lambda *args: {})
    source = tmp_path / "input" / "ventas.csv"
    source.write_text("Fecha;Producto;Cant.;P. Unit.\n10/09/2026;Coca;12;$ 1.890,00\n", encoding="utf-8")
    sent = []
    _mock_backend(monkeypatch, sent)
    mapping = {"fecha": "Fecha", "producto_nombre": "Producto", "cantidad_vendida": "Cant.", "precio_venta": "P. Unit."}
    save_source_preview(preview_source(source, mapping, price="final_net", discount="per_line"))
    # Simulamos el estado que deja RC8: el archivo quedo rechazado por esa version.
    config = load_config(config_path)
    with connect(local_db_path(config)) as conn:
        conn.execute("UPDATE processed_files SET status='error'")
    import aiva_collector.cli as cli
    monkeypatch.setattr(cli, "_process_reliable_file", _rejecting(cli._process_reliable_file))
    assert main(["run-auto", "--config", str(config_path)]) == 2
    with connect(local_db_path(config)) as conn:
        conn.execute("UPDATE processed_file_events SET context_json='{\"collector_version\": \"0.2.8rc8\"}' WHERE event_type='processing_error'")
        conn.commit()
    monkeypatch.undo()
    monkeypatch.setenv("AIVA_COLLECTOR_STANDARD_CONFIG", str(config_path))
    monkeypatch.setenv("AIVA_COLLECTOR_DATA_DIR", str(tmp_path / "programdata"))
    monkeypatch.setattr("aiva_collector.cli.CollectorClient.post_mapping_candidate", lambda *args: {})
    _mock_backend(monkeypatch, sent)
    assert main(["run-auto", "--config", str(config_path)]) == 0
    assert len(sent) == 1
    assert sent[0]["resumen_financiero"]["facturacion_total"] == 12 * 1890
    # Una sola vez: una segunda corrida no lo vuelve a mandar.
    assert main(["run-auto", "--config", str(config_path)]) == 0
    assert len(sent) == 1


def _rejecting(original):
    def process(*, config, client, conn, path, backend_mapping, **kwargs):
        from aiva_collector.local_state import add_event, upsert_detected_file
        from aiva_collector.file_fingerprint import build_file_id, compute_file_sha256
        from aiva_collector.cli import _backend_target, VERSION
        digest = compute_file_sha256(path)
        file_id = build_file_id(digest, path.name, commerce_id=config.commerce_id, collector_id=config.collector_id,
                                backend_url=_backend_target(config), source_id=config.raw.get("daily_source_id"))
        upsert_detected_file(conn, file_id=file_id, commerce_id=config.commerce_id, collector_id=config.collector_id,
                             backend_url=_backend_target(config), path=path, file_sha256=digest, status="error",
                             source_id=config.raw.get("daily_source_id"))
        add_event(conn, file_id=file_id, event_type="processing_error", level="error", message="precio_venta requerido",
                  context={"collector_version": VERSION})
        return "error", "precio_venta requerido"
    return process
