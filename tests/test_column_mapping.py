import json
from pathlib import Path

from aiva_collector.column_mapping import detect_column_mapping, validate_explicit_mapping
from aiva_collector.cli import main


def test_technical_headers_map_perfectly():
    headers = [
        "fecha",
        "producto_codigo",
        "producto_nombre",
        "categoria",
        "cantidad_vendida",
        "precio_venta",
        "costo_unitario",
        "stock_actual",
    ]
    result = detect_column_mapping(headers)
    assert result.status == "auto_approved"
    assert result.confidence >= 0.95
    assert result.mapping["producto_nombre"] == "producto_nombre"


def test_simple_headers_map_perfectly():
    result = detect_column_mapping(["fecha", "codigo", "producto", "categoria", "cantidad", "precio", "costo", "stock"])
    assert result.status == "auto_approved"
    assert result.mapping["producto_nombre"] == "producto"
    assert result.mapping["cantidad_vendida"] == "cantidad"
    assert result.mapping["precio_venta"] == "precio"


def test_commerce_headers_map_well():
    result = detect_column_mapping(["Fecha Venta", "Artículo", "Descripción", "Cant.", "Precio Unit.", "Costo Compra", "Existencia", "Rubro"])
    assert result.status == "auto_approved"
    assert result.mapping["producto_codigo"] == "Artículo"
    assert result.mapping["producto_nombre"] == "Descripción"
    assert result.mapping["cantidad_vendida"] == "Cant."
    assert result.mapping["precio_venta"] == "Precio Unit."


def test_confusing_headers_need_review_or_fail():
    result = detect_column_mapping(["Cliente", "Documento", "Observaciones"])
    assert result.status in {"needs_review", "failed"}
    assert "producto_nombre" in result.missing_required


def test_explicit_mapping_has_priority_when_valid():
    result = validate_explicit_mapping(
        {"producto_nombre": "Nombre Comercial", "cantidad_vendida": "Unidades", "precio_venta": "PVP"},
        ["Nombre Comercial", "Unidades", "PVP", "Descripción"],
    )
    assert result.status == "auto_approved"
    assert result.mapping["producto_nombre"] == "Nombre Comercial"


def test_dry_run_shows_mapping_used(tmp_path, capsys):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "ventas.csv").write_text("Fecha Venta,Artículo,Descripción,Cant.,Precio Unit.\n2026-06-01,A1,Coca,2,10\n", encoding="utf-8")
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
    assert main(["run-once", "--config", str(config_path)]) == 0
    assert "mapping usado" in capsys.readouterr().out
