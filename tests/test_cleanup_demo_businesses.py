import importlib.util
import json
import sys
from pathlib import Path


SCRIPT_PATH = Path("scripts/cleanup_demo_businesses.py")
SPEC = importlib.util.spec_from_file_location("cleanup_demo_businesses", SCRIPT_PATH)
cleanup = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = cleanup
SPEC.loader.exec_module(cleanup)


def _business(
    commerce_id,
    display_name,
    created_at,
    *,
    activation_state="active",
    is_enabled=True,
    collector_token=None,
):
    data = {
        "commerce_id": commerce_id,
        "display_name": display_name,
        "created_at": created_at,
        "activation_state": activation_state,
        "is_enabled": is_enabled,
    }
    if collector_token:
        data["collector_token"] = collector_token
    return data


def test_identifies_demos_by_exact_prefix_only():
    businesses = [
        _business("demo_1", "Demo Integracion Collector AIVA", "2026-06-19T03:00:00Z"),
        _business("demo_2", "Demo Integracion Collector AIVA viejo", "2026-06-19T02:00:00Z"),
        _business("similar", "Demo Integración Collector AIVA", "2026-06-19T01:00:00Z"),
        _business("real", "Cliente Real", "2026-06-19T00:00:00Z"),
    ]
    demos = cleanup.sorted_demo_businesses(businesses)
    assert [item["commerce_id"] for item in demos] == ["demo_1", "demo_2"]


def test_keep_latest_keeps_newest_demo_and_excludes_real_commerces():
    plan = cleanup.build_cleanup_plan(
        [
            _business("real", "Cliente Real", "2026-06-19T05:00:00Z"),
            _business("old", "Demo Integracion Collector AIVA old", "2026-06-19T01:00:00Z"),
            _business("new", "Demo Integracion Collector AIVA new", "2026-06-19T02:00:00Z"),
        ],
        keep_latest=1,
    )
    assert [item["commerce_id"] for item in plan.kept] == ["new"]
    assert [item["commerce_id"] for item in plan.candidates] == ["old"]
    assert all(item["commerce_id"] != "real" for item in plan.demos + plan.kept + plan.candidates)


def test_keep_commerce_id_keeps_indicated_demo():
    plan = cleanup.build_cleanup_plan(
        [
            _business("old", "Demo Integracion Collector AIVA old", "2026-06-19T01:00:00Z"),
            _business("new", "Demo Integracion Collector AIVA new", "2026-06-19T02:00:00Z"),
        ],
        keep_latest=0,
        keep_commerce_ids={"old"},
    )
    assert [item["commerce_id"] for item in plan.kept] == ["old"]
    assert [item["commerce_id"] for item in plan.candidates] == ["new"]


def test_dry_run_does_not_call_deactivate(monkeypatch):
    monkeypatch.setattr(
        cleanup,
        "list_businesses",
        lambda base_url, secret: [
            _business("keep", "Demo Integracion Collector AIVA keep", "2026-06-19T02:00:00Z"),
            _business("old", "Demo Integracion Collector AIVA old", "2026-06-19T01:00:00Z"),
        ],
    )
    calls = []
    monkeypatch.setattr(cleanup, "deactivate_business", lambda *args: calls.append(args))
    plan, results = cleanup.run_cleanup(
        base_url="http://backend",
        secret="secret",
        confirm=False,
        keep_latest=1,
        keep_commerce_ids=set(),
        prefix=cleanup.DEFAULT_PREFIX,
        max_to_deactivate=20,
        include_inactive=False,
    )
    assert [item["commerce_id"] for item in plan.candidates] == ["old"]
    assert results == []
    assert calls == []


def test_confirm_deactivates_only_candidates(monkeypatch):
    monkeypatch.setattr(
        cleanup,
        "list_businesses",
        lambda base_url, secret: [
            _business("keep", "Demo Integracion Collector AIVA keep", "2026-06-19T03:00:00Z"),
            _business("old", "Demo Integracion Collector AIVA old", "2026-06-19T02:00:00Z"),
            _business("real", "Cliente Real", "2026-06-19T01:00:00Z"),
        ],
    )
    calls = []

    def fake_deactivate(base_url, secret, commerce_id):
        calls.append((base_url, secret, commerce_id))
        return {"ok": True}

    monkeypatch.setattr(cleanup, "deactivate_business", fake_deactivate)
    _plan, results = cleanup.run_cleanup(
        base_url="http://backend",
        secret="secret",
        confirm=True,
        keep_latest=1,
        keep_commerce_ids=set(),
        prefix=cleanup.DEFAULT_PREFIX,
        max_to_deactivate=20,
        include_inactive=False,
    )
    assert calls == [("http://backend", "secret", "old")]
    assert results == [{"commerce_id": "old", "status": "deactivated"}]


def test_max_to_deactivate_limits_actions(monkeypatch):
    monkeypatch.setattr(
        cleanup,
        "list_businesses",
        lambda base_url, secret: [
            _business("keep", "Demo Integracion Collector AIVA keep", "2026-06-19T04:00:00Z"),
            _business("old_3", "Demo Integracion Collector AIVA old 3", "2026-06-19T03:00:00Z"),
            _business("old_2", "Demo Integracion Collector AIVA old 2", "2026-06-19T02:00:00Z"),
            _business("old_1", "Demo Integracion Collector AIVA old 1", "2026-06-19T01:00:00Z"),
        ],
    )
    calls = []
    monkeypatch.setattr(cleanup, "deactivate_business", lambda base_url, secret, commerce_id: calls.append(commerce_id))
    plan, _results = cleanup.run_cleanup(
        base_url="http://backend",
        secret="secret",
        confirm=True,
        keep_latest=1,
        keep_commerce_ids=set(),
        prefix=cleanup.DEFAULT_PREFIX,
        max_to_deactivate=2,
        include_inactive=False,
    )
    assert calls == ["old_3", "old_2"]
    assert plan.truncated is True


def test_include_inactive_only_affects_visibility_not_candidates():
    businesses = [
        _business("new", "Demo Integracion Collector AIVA new", "2026-06-19T03:00:00Z"),
        _business("inactive", "Demo Integracion Collector AIVA inactive", "2026-06-19T02:00:00Z", activation_state="inactive"),
        _business("disabled", "Demo Integracion Collector AIVA disabled", "2026-06-19T01:00:00Z", is_enabled=False),
    ]
    hidden = cleanup.build_cleanup_plan(businesses, keep_latest=1, include_inactive=False)
    visible = cleanup.build_cleanup_plan(businesses, keep_latest=1, include_inactive=True)
    assert [item["commerce_id"] for item in hidden.candidates] == []
    assert [item["commerce_id"] for item in visible.candidates] == []
    assert hidden.inactive == []
    assert [item["commerce_id"] for item in visible.inactive] == ["inactive", "disabled"]


def test_human_output_does_not_print_secrets(capsys):
    secret = "super-secret"
    plan = cleanup.build_cleanup_plan(
        [
            _business(
                "old",
                "Demo Integracion Collector AIVA old",
                "2026-06-19T01:00:00Z",
                collector_token="collector-secret",
            )
        ],
        keep_latest=0,
    )
    cleanup.print_human_plan(plan, mode="dry-run")
    output = cleanup.mask_sensitive(capsys.readouterr().out, [secret, "collector-secret"])
    assert secret not in output
    assert "collector-secret" not in output


def test_json_output_does_not_include_secrets():
    plan = cleanup.build_cleanup_plan(
        [
            _business(
                "old",
                "Demo Integracion Collector AIVA old",
                "2026-06-19T01:00:00Z",
                collector_token="collector-secret",
            )
        ],
        keep_latest=0,
    )
    encoded = json.dumps(cleanup.plan_to_json(plan, mode="dry-run"))
    assert "collector-secret" not in encoded
    assert "collector_token" not in encoded


def test_cleanup_never_calls_create_collector_summary_or_report(monkeypatch):
    requested = []

    def fake_request(method, url, **kwargs):
        requested.append((method, url))
        if method == "GET" and url.endswith("/admin/commerce/businesses"):
            return {"businesses": [_business("old", "Demo Integracion Collector AIVA old", "2026-06-19T01:00:00Z")]}
        if method == "POST" and url.endswith("/deactivate"):
            return {"ok": True}
        raise AssertionError(f"unexpected request {method} {url}")

    monkeypatch.setattr(cleanup, "_request_json", fake_request)
    cleanup.run_cleanup(
        base_url="http://backend",
        secret="secret",
        confirm=True,
        keep_latest=0,
        keep_commerce_ids=set(),
        prefix=cleanup.DEFAULT_PREFIX,
        max_to_deactivate=20,
        include_inactive=False,
    )
    urls = [url for _method, url in requested]
    assert urls == [
        "http://backend/admin/commerce/businesses",
        "http://backend/admin/commerce/businesses/old/deactivate",
    ]
    assert all("/collectors" not in url for url in urls)
    assert all("/summaries" not in url for url in urls)
    assert all("/reports" not in url for url in urls)
