import pytest

from aiva_collector.client import CollectorClient, _headers
from aiva_collector.client import activate_collector
from aiva_collector.config import load_config
from aiva_collector.errors import BackendError


def test_headers_do_not_print_token(monkeypatch, capsys):
    monkeypatch.setenv("AIVA_COLLECTOR_TOKEN", "super-secret-token")
    config = load_config("configs/example_config.json")
    headers = _headers(config, "idem")
    captured = capsys.readouterr()
    assert "super-secret-token" not in captured.out
    assert "super-secret-token" not in captured.err
    assert headers["Authorization"] == "Bearer super-secret-token"


def test_headers_require_token(monkeypatch):
    monkeypatch.delenv("AIVA_COLLECTOR_TOKEN", raising=False)
    config = load_config("configs/example_config.json")
    with pytest.raises(BackendError, match="Falta token"):
        _headers(config)


def test_backend_error_carries_status_code(monkeypatch):
    monkeypatch.setenv("AIVA_COLLECTOR_TOKEN", "super-secret-token")
    config = load_config("configs/example_config.json")

    class Response:
        status_code = 409
        content = b'{"error":{"code":"duplicate_summary"}}'
        text = '{"error":{"code":"duplicate_summary"}}'

        def json(self):
            return {"error": {"code": "duplicate_summary"}}

    monkeypatch.setattr("aiva_collector.client.requests.post", lambda *args, **kwargs: Response())
    with pytest.raises(BackendError) as exc:
        CollectorClient(config).send_summary(
            {
                "commerce_id": "commerce_demo",
                "collector_id": "collector_demo",
                "fecha_inicio": "2026-06-01",
                "fecha_fin": "2026-06-07",
                "productos_resumidos": [],
            }
        )
    assert exc.value.status_code == 409


def test_service_status_sends_collector_identifiers(monkeypatch):
    monkeypatch.setenv("AIVA_COLLECTOR_TOKEN", "super-secret-token")
    config = load_config("configs/example_config.json")
    captured = {}

    class Response:
        status_code = 200
        content = b"{}"

        def json(self):
            return {}

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return Response()

    monkeypatch.setattr("aiva_collector.client.requests.get", fake_get)
    assert CollectorClient(config).service_status() == {}
    assert captured["kwargs"]["params"] == {
        "commerce_id": "commerce_demo",
        "collector_id": "collector_demo",
    }


def test_post_status_uses_backend_error_message_field(monkeypatch):
    monkeypatch.setenv("AIVA_COLLECTOR_TOKEN", "super-secret-token")
    config = load_config("configs/example_config.json")
    captured = {}

    class Response:
        status_code = 200
        content = b"{}"

        def json(self):
            return {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return Response()

    monkeypatch.setattr("aiva_collector.client.requests.post", fake_post)
    CollectorClient(config).post_status("error", "archivo invalido")
    assert captured["kwargs"]["json"]["error_message"] == "archivo invalido"
    assert "message" not in captured["kwargs"]["json"]


def test_activate_collector_posts_code_without_printing_token(monkeypatch, capsys):
    captured = {}

    class Response:
        status_code = 200
        content = b'{"ok": true, "collector_token": "aiva_col_secret"}'

        def json(self):
            return {"ok": True, "collector_token": "aiva_col_secret"}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return Response()

    monkeypatch.setattr("aiva_collector.client.requests.post", fake_post)
    response = activate_collector(
        backend_url="http://backend",
        activation_code="AIVA-TEST-0001",
        machine_id="machine",
        hostname="host",
        collector_version="0.2.0",
    )

    assert response["collector_token"] == "aiva_col_secret"
    assert captured["url"] == "http://backend/commerce/collector/activate"
    assert captured["kwargs"]["json"]["activation_code"] == "AIVA-TEST-0001"
    assert "aiva_col_secret" not in capsys.readouterr().out
