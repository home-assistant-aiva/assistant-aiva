import json

import pytest

from aiva_collector.config import ConfigError, load_config


def test_load_config_example():
    config = load_config("configs/example_config.json")
    assert config.commerce_id == "commerce_demo"
    assert config.token is None


def test_config_rejects_token_in_file(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(
        json.dumps(
            {
                "commerce_id": "c",
                "collector_id": "k",
                "collector_token": "secret",
                "column_mapping": {
                    "producto_nombre": "n",
                    "cantidad_vendida": "q",
                    "precio_venta": "p",
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_config(path)


def test_send_requires_token(monkeypatch):
    monkeypatch.delenv("AIVA_COLLECTOR_TOKEN", raising=False)
    config = load_config("configs/example_config.json")
    with pytest.raises(ConfigError, match="Falta token"):
        config.require_send_ready()


def test_dry_run_allows_missing_token(monkeypatch):
    monkeypatch.delenv("AIVA_COLLECTOR_TOKEN", raising=False)
    config = load_config("configs/example_config.json")
    assert config.token is None
