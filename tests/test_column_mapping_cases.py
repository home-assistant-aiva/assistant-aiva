from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from aiva_collector.cli import main
from aiva_collector.column_mapping import detect_column_mapping, validate_explicit_mapping
from aiva_collector.config import CollectorConfig
from aiva_collector.readers import read_file


CASES_DIR = Path("samples/mapping_cases")


def _headers_for_case(name: str) -> list[str]:
    path = CASES_DIR / name
    rows = read_file(path, CollectorConfig(raw={"encoding": "utf-8", "delimiter": ","}, config_path=Path("test.json")))
    return list(rows[0].keys())


def _result(name: str):
    return detect_column_mapping(_headers_for_case(name))


def _config_for_single_case(tmp_path: Path, case_name: str) -> Path:
    input_dir = tmp_path / "input"
    input_dir.mkdir(parents=True)
    shutil.copy2(CASES_DIR / case_name, input_dir / case_name)
    data = json.loads(Path("configs/example_config.json").read_text(encoding="utf-8"))
    data.update(
        {
            "input_dir": str(input_dir),
            "processed_dir": str(tmp_path / "processed"),
            "error_dir": str(tmp_path / "error"),
            "output_dir": str(tmp_path / "output"),
            "state_dir": str(tmp_path / "state"),
            "log_file": str(tmp_path / "logs" / "aiva_collector.log"),
        }
    )
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(data), encoding="utf-8")
    return config_path


def _assert_no_duplicate_sources(mapping: dict[str, str]) -> None:
    assert len(mapping.values()) == len(set(mapping.values()))


def test_technical_columns_case_auto_approved():
    result = _result("technical_columns.xlsx")
    assert result.status == "auto_approved"
    assert not result.missing_required
    assert result.confidence >= 0.95
    _assert_no_duplicate_sources(result.mapping)


def test_simple_columns_case_auto_approved():
    result = _result("simple_columns.xlsx")
    assert result.status == "auto_approved"
    assert not result.missing_required


def test_pos_spanish_columns_case_auto_approved():
    result = _result("pos_spanish_columns.xlsx")
    assert result.status == "auto_approved"
    assert result.mapping["producto_nombre"] == "Descripción"
    assert result.mapping["producto_codigo"] == "Código Artículo"


def test_accented_columns_case_auto_approved():
    result = _result("accented_columns.csv")
    assert result.status == "auto_approved"
    assert result.mapping["fecha"] == "Día"
    assert result.mapping["categoria"] == "Categoría"


def test_english_columns_case_confident():
    result = _result("english_columns.xlsx")
    assert result.status == "auto_approved"
    assert result.confidence >= 0.80
    assert result.mapping["categoria"] == "category"
    assert result.mapping["stock_actual"] == "inventory"


def test_messy_but_mappable_case_confident_required_ok():
    result = _result("messy_but_mappable.xlsx")
    assert result.confidence >= 0.75
    assert not result.missing_required
    assert result.mapping["cantidad_vendida"] == "Unid. Vend."
    assert result.mapping["precio_venta"] == "$ Precio Venta"


def test_low_confidence_case_needs_review_or_failed():
    result = _result("low_confidence_columns.xlsx")
    assert result.status in {"needs_review", "failed"}
    assert result.status != "auto_approved"


def test_missing_required_case_fails_with_quantity_and_price():
    result = _result("missing_required_columns.xlsx")
    assert result.status == "failed"
    assert "cantidad_vendida" in result.missing_required
    assert "precio_venta" in result.missing_required


def test_explicit_mapping_still_has_priority_for_case_headers():
    result = validate_explicit_mapping(
        {
            "producto_nombre": "Descripción",
            "cantidad_vendida": "Cant.",
            "precio_venta": "Precio Unit.",
        },
        _headers_for_case("pos_spanish_columns.xlsx"),
    )
    assert result.status == "auto_approved"
    assert result.mapping["producto_nombre"] == "Descripción"


def test_detector_does_not_import_gpt_or_backend_clients():
    before = set(sys.modules)
    result = _result("technical_columns.xlsx")
    loaded = set(sys.modules) - before
    assert result.status == "auto_approved"
    assert "openai" not in loaded
    assert "requests" not in loaded


def test_dry_run_mapping_cases_show_mapping_used(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("AIVA_COLLECTOR_TOKEN", raising=False)
    for case_name in ("technical_columns.xlsx", "simple_columns.xlsx", "pos_spanish_columns.xlsx"):
        config_path = _config_for_single_case(tmp_path / case_name.replace(".", "_"), case_name)
        assert main(["run-once", "--config", str(config_path)]) == 0
        captured = capsys.readouterr()
        assert "mapping usado" in captured.out
        assert "aiva_col_" not in captured.out
        assert "aiva_col_" not in captured.err


def test_dry_run_low_confidence_case_fails_clear_without_token_or_traceback(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("AIVA_COLLECTOR_TOKEN", raising=False)
    config_path = _config_for_single_case(tmp_path, "low_confidence_columns.xlsx")
    assert main(["run-once", "--config", str(config_path)]) == 2
    captured = capsys.readouterr()
    assert "AIVA necesita revisar el mapeo de columnas desde el admin" in captured.err
    assert "Traceback" not in captured.err
    assert "aiva_col_" not in captured.err


def test_dry_run_missing_required_case_fails_clear_without_traceback(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("AIVA_COLLECTOR_TOKEN", raising=False)
    config_path = _config_for_single_case(tmp_path, "missing_required_columns.xlsx")
    assert main(["run-once", "--config", str(config_path)]) == 2
    captured = capsys.readouterr()
    assert "AIVA necesita revisar el mapeo de columnas desde el admin" in captured.err
    assert "Traceback" not in captured.err
