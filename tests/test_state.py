import json

from aiva_collector.config import CollectorConfig
from aiva_collector.state import save_state


def test_save_state_includes_backend_fields_without_secrets(tmp_path):
    config = CollectorConfig(
        raw={
            "commerce_id": "commerce_demo",
            "collector_id": "collector_demo",
            "collector_token_env": "AIVA_COLLECTOR_TOKEN",
            "state_dir": str(tmp_path),
            "column_mapping": {
                "producto_nombre": "producto_nombre",
                "cantidad_vendida": "cantidad_vendida",
                "precio_venta": "precio_venta",
            },
        },
        config_path=tmp_path / "config.json",
    )

    path = save_state(
        config,
        last_summary_file="samples/output/last_summary.json",
        last_idempotency_key_hash="hash",
        last_status="ok",
        backend_state={
            "last_backend_send_at": "2026-06-19T00:00:00+00:00",
            "last_backend_status_code": 200,
            "last_backend_summary_status": "sent",
            "last_backend_report_id": "report_demo",
            "last_backend_commerce_id": "commerce_demo",
            "last_backend_collector_id": "collector_demo",
            "last_idempotency_key_hash": "hash",
            "idempotency_confirmed": True,
            "collector_token": "secret-token",
            "token_hash": "secret-hash",
        },
    )

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["last_backend_status_code"] == 200
    assert data["last_backend_summary_status"] == "sent"
    assert data["last_backend_report_id"] == "report_demo"
    assert data["idempotency_confirmed"] is True
    rendered = json.dumps(data)
    assert "secret-token" not in rendered
    assert "secret-hash" not in rendered
    assert "collector_token" not in data
    assert "token_hash" not in data
