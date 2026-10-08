"""Regression cases found while reviewing the RC9 candidate."""
from aiva_collector.daily import stable_product_code


def test_synthetic_code_does_not_confuse_name_and_category_delimiters():
    first = {"producto_nombre": "A|B", "categoria": "C"}
    second = {"producto_nombre": "A", "categoria": "B|C"}
    assert stable_product_code(first) != stable_product_code(second)


def test_crash_recovery_only_releases_the_active_backend_and_source(tmp_path):
    from aiva_collector.cli import _backend_target, _release_file_after_crash
    from aiva_collector.config import load_config
    from aiva_collector.local_state import connect, local_db_path, upsert_detected_file, update_file_state
    from test_collector_deduplication import _config

    config = load_config(_config(tmp_path))
    config.raw["daily_source_id"] = "active-source"
    path = tmp_path / "input" / "ventas.csv"
    path.write_text("test")
    active_backend = _backend_target(config)
    contexts = [("active", active_backend, "active-source"),
                ("other-backend", "https://another-backend.example", "active-source"),
                ("other-source", active_backend, "other-source")]
    with connect(local_db_path(config)) as conn:
        for file_id, backend, source in contexts:
            upsert_detected_file(conn, file_id=file_id, commerce_id=config.commerce_id,
                                 collector_id=config.collector_id, backend_url=backend,
                                 source_id=source, path=path, file_sha256=file_id)
            update_file_state(conn, file_id, status="processing", lease_expires_at="2099-01-01T00:00:00+00:00")
        _release_file_after_crash(conn, config, path, "retry")
        leases = {row["file_id"]: row["lease_expires_at"] for row in conn.execute("SELECT file_id, lease_expires_at FROM processed_files")}
    assert leases["active"] is None
    assert leases["other-backend"] is not None
    assert leases["other-source"] is not None
