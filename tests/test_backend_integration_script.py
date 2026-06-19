import importlib.util
import json
from pathlib import Path


SCRIPT_PATH = Path("scripts/backend_integration_demo.py")
SPEC = importlib.util.spec_from_file_location("backend_integration_demo", SCRIPT_PATH)
backend_integration_demo = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(backend_integration_demo)


def test_mask_sensitive_hides_known_secrets():
    text = "secret=abc123 Authorization: Bearer token-456"
    masked = backend_integration_demo.mask_sensitive(text, ["abc123", "token-456"])
    assert "abc123" not in masked
    assert "token-456" not in masked
    assert "[MASKED]" in masked


def test_write_temp_config_does_not_store_token():
    path = backend_integration_demo.write_temp_config("http://127.0.0.1:8080", "commerce_x", "collector_y")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    finally:
        path.unlink(missing_ok=True)
    assert data["commerce_id"] == "commerce_x"
    assert data["collector_id"] == "collector_y"
    assert data["collector_token_env"] == "AIVA_COLLECTOR_TOKEN"
    assert "collector_token" not in data


def test_extract_required_finds_nested_ids():
    payload = {"business": {"commerce_id": "commerce_demo"}, "collector": {"collector_id": "collector_demo"}}
    assert backend_integration_demo.extract_required(payload, {"commerce_id", "id"}, "commerce_id") == "commerce_demo"
    assert backend_integration_demo.extract_required(payload, {"collector_id", "id"}, "collector_id") == "collector_demo"


def test_recommendations_count_accepts_list_and_explicit_count():
    assert backend_integration_demo.recommendations_count({"recommendations_count": "2"}) == 2
    assert backend_integration_demo.recommendations_count({"recommendations": [{"id": 1}, {"id": 2}]}) == 2


def test_demo_detection_and_latest_sorting():
    payload = {
        "businesses": [
            {"commerce_id": "commerce_real", "display_name": "Cliente Real", "created_at": "2026-06-19T01:00:00Z"},
            {
                "commerce_id": "commerce_old",
                "display_name": "Demo Integracion Collector AIVA",
                "created_at": "2026-06-19T01:00:00Z",
            },
            {
                "commerce_id": "commerce_new",
                "display_name": "Demo Integracion Collector AIVA 2",
                "created_at": "2026-06-19T02:00:00Z",
            },
        ]
    }
    demos = backend_integration_demo.find_demo_businesses(payload)
    assert [item["commerce_id"] for item in demos] == ["commerce_new", "commerce_old"]
    assert backend_integration_demo.latest_demo_business(payload)["commerce_id"] == "commerce_new"


def test_idempotency_key_hash_does_not_return_key():
    digest = backend_integration_demo.idempotency_key_hash("idem-secret")
    assert digest != "idem-secret"
    assert len(digest) == 64


def test_main_parses_new_flags(monkeypatch):
    captured = {}

    def fake_run(base_url, **kwargs):
        captured["base_url"] = base_url
        captured["kwargs"] = kwargs
        return {"ok": True}

    monkeypatch.setattr(backend_integration_demo, "run_integration", fake_run)
    code = backend_integration_demo.main(
        [
            "--base-url",
            "http://backend",
            "--reuse-latest-demo",
            "--test-idempotency",
            "--force-new-demo",
        ]
    )
    assert code == 0
    assert captured["base_url"] == "http://backend"
    assert captured["kwargs"] == {
        "reuse_latest_demo": True,
        "test_idempotency": True,
        "deactivate_old_demos_flag": False,
        "force_new_demo": True,
    }


def test_deactivate_old_demos_flag_is_safe_alias(monkeypatch, capsys):
    called = False

    def fake_run(*args, **kwargs):
        nonlocal called
        called = True
        return {"ok": True}

    monkeypatch.setattr(backend_integration_demo, "run_integration", fake_run)
    code = backend_integration_demo.main(
        ["--deactivate-old-demos", "--reuse-latest-demo", "--test-idempotency", "--force-new-demo"]
    )
    output = capsys.readouterr().out
    assert code == 0
    assert called is False
    assert "cleanup_demo_businesses.sh --dry-run" in output


def test_idempotency_flow_mocked(monkeypatch):
    monkeypatch.setenv("AIVA_INTERNAL_SECRET", "internal-secret")
    calls = {"send": 0}

    def fake_request(method, url, **kwargs):
        if url.endswith("/health"):
            return {"ok": True}
        if method == "GET" and url.endswith("/admin/commerce/businesses"):
            return {"businesses": []}
        if method == "POST" and url.endswith("/admin/commerce/businesses"):
            return {"business": {"commerce_id": "commerce_demo"}}
        if method == "POST" and url.endswith("/activate"):
            return {"ok": True}
        if method == "POST" and url.endswith("/collectors"):
            return {"collector": {"collector_id": "collector_demo"}, "collector_token": "collector-token"}
        if method == "GET" and url.endswith("/ingestion-summaries"):
            return {"summaries": [{"period_start": "2026-06-01", "period_end": "2026-06-07", "product_count": 2}]}
        if method == "GET" and url.endswith("/audit"):
            return {
                "audit": {
                    "summaries_count": 1,
                    "recommendations_count": 3,
                    "reports_count": 0,
                    "last_report_id": None,
                }
            }
        if method == "GET" and url.endswith("/recommendations"):
            return {"recommendations": [{"id": 1}]}
        if method == "POST" and url.endswith("/reports/generate"):
            return {"report_id": "report_demo", "status": "generated", "report_text": "Reporte"}
        if method == "GET" and url.endswith("/latest-report"):
            return {"report": {"report_id": "report_demo"}}
        raise AssertionError(f"unexpected request {method} {url}")

    def fake_send(*args, **kwargs):
        calls["send"] += 1
        return "sent" if calls["send"] == 1 else "duplicate_summary"

    monkeypatch.setattr(backend_integration_demo, "_request_json", fake_request)
    monkeypatch.setattr(backend_integration_demo, "run_collector_command", lambda *args, **kwargs: None)
    monkeypatch.setattr(backend_integration_demo, "run_send", fake_send)
    result = backend_integration_demo.run_integration("http://backend", test_idempotency=True, force_new_demo=True)
    assert result["first_send_status"] == "sent"
    assert result["second_send_status"] == "duplicate_summary"
    assert result["idempotency_confirmed"] is True
