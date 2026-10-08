"""RC9: configuracion guiada con numeros argentinos, sin codigo y con la tabla."""
import json
from decimal import Decimal

import pytest

from aiva_collector.config import load_config
from aiva_collector.errors import ValidationError
from aiva_collector.source_setup import (
    interpret_sample,
    preview_source,
    save_source_preview,
    suggest_mapping,
    inspect_source,
)
from test_collector_deduplication import _config, _mock_backend

MAPPING = {"fecha": "Fecha", "producto_nombre": "Producto", "categoria": "Rubro",
           "cantidad_vendida": "Cant.", "precio_venta": "P. Unit."}


def _semana(*, extra_lines=(), header="Fecha;Producto;Rubro;Cant.;P. Unit.;Importe"):
    lines = [header]
    real = Decimal(0)
    for day in range(10, 17):
        lines.append(f"{day:02d}/09/2026;Coca-Cola 2.25L;Bebidas;12;$ 1.890,00;$ 22.680,00")
        lines.append(f"{day:02d}/09/2026;Alfajor Jorgito;Golosinas;20;2.450;49.000")
        real += 12 * 1890 + 20 * 2450
    lines.extend(extra_lines)
    return "\n".join(lines) + "\n", real


@pytest.fixture
def fuente(tmp_path, monkeypatch):
    config_path = _config(tmp_path, move_processed=False)
    config = json.loads(config_path.read_text())
    config.update(source_read_only=True, move_error_files=False)
    config_path.write_text(json.dumps(config))
    monkeypatch.setenv("AIVA_COLLECTOR_STANDARD_CONFIG", str(config_path))
    monkeypatch.setenv("AIVA_COLLECTOR_DATA_DIR", str(tmp_path / "programdata"))
    monkeypatch.setattr("aiva_collector.cli.CollectorClient.post_mapping_candidate", lambda *args: {})
    source = tmp_path / "input" / "ventas.csv"
    text, real = _semana(extra_lines=[";;;;;", "TOTAL;;;224;;$ 501.760,00"])
    source.write_text(text, encoding="utf-8")
    return config_path, source, real


def test_sugerencia_y_tabla_de_una_exportacion_argentina(fuente):
    _, source, _ = fuente
    headers, rows = inspect_source(source)
    suggestion = suggest_mapping(headers, rows)
    for field, column in MAPPING.items():
        assert suggestion.mapping.get(field) == column
    sample = interpret_sample(source, suggestion.mapping)
    prices = [row["cells"][sample["fields"].index("precio_venta")] for row in sample["rows"]]
    assert "$ 1.890,00 → 1.890" in prices and "2.450" in prices
    assert not any(row["problem"] for row in sample["rows"])
    assert sample["total_rows"] == 14 and sample["skipped_total_rows"] == 1
    price_report = next(item for item in sample["numbers"] if item["field"] == "precio_venta")
    assert price_report["convention"] == "comma" and "se lee como 1.890" in price_report["example"]
    assert any(w.startswith("Control superado") for w in sample["warnings"])


def test_vista_previa_sin_codigo_con_totales_reales_y_formato_congelado(fuente, monkeypatch):
    from aiva_collector.cli import main
    config_path, source, real = fuente
    preview = preview_source(source, MAPPING, price="final_net", discount="per_line", complete=True)
    assert Decimal(preview["totals"]["ventas_netas"]) == real
    assert preview["totals_display"]["ventas_netas"] == "$ 501.760"
    assert preview["products_without_code"] == 2
    assert len(preview["skipped_total_rows"]) == 1
    save_source_preview(preview)
    saved = load_config(config_path).raw
    assert saved["decimal_conventions"]["precio_venta"] == "comma"
    sent = []
    _mock_backend(monkeypatch, sent)
    assert main(["run-auto", "--config", str(config_path)]) == 0
    snapshot = sent[0]["daily_snapshot"]
    assert sum(Decimal(m["net_revenue"]) for m in snapshot["metrics"]) == real
    assert all(m["product_code"].startswith("name_hash:") for m in snapshot["metrics"])


def test_formato_elegido_a_mano_falla_con_fila_y_columna(fuente):
    # Con punto decimal "$ 1.890,00" no se puede leer: se informa la fila, no se adivina.
    _, source, _ = fuente
    with pytest.raises(ValidationError) as error:
        preview_source(source, MAPPING, price="final_net", discount="per_line", number_format="dot")
    assert "Fila 2, columna 'P. Unit.' = '$ 1.890,00'" in str(error.value)


def test_falta_columna_obligatoria_y_columna_repetida(fuente):
    _, source, _ = fuente
    with pytest.raises(ValidationError, match="Cantidad"):
        preview_source(source, {**MAPPING, "cantidad_vendida": ""}, price="final_net", discount="per_line")
    with pytest.raises(ValidationError, match="'Producto' está elegida para"):
        preview_source(source, {**MAPPING, "categoria": "Producto"}, price="final_net", discount="per_line")


def test_zona_horaria_invalida(fuente):
    _, source, _ = fuente
    with pytest.raises(ValidationError, match="zona horaria"):
        preview_source(source, MAPPING, price="final_net", discount="per_line", timezone_name="Marte/Olympus")


def test_precio_que_en_realidad_es_el_total_de_la_linea(fuente):
    _, source, _ = fuente
    mapping = {**MAPPING, "precio_venta": "Importe"}
    sample = interpret_sample(source, mapping)
    assert any("parece ser el total de la línea" in warning and "'P. Unit.'" in warning for warning in sample["warnings"])


def test_cantidad_y_precio_invertidos(fuente):
    _, source, _ = fuente
    sample = interpret_sample(source, {**MAPPING, "cantidad_vendida": "P. Unit.", "precio_venta": "Cant."})
    assert any("invertidos" in warning for warning in sample["warnings"])


def test_fechas_de_eeuu_se_avisan(tmp_path, fuente):
    _, source, _ = fuente
    source.write_text("Fecha;Producto;Cant.;P. Unit.\n09/25/2026;Coca;1;1890\n09/26/2026;Yerba;1;3200\n", encoding="utf-8")
    sample = interpret_sample(source, {"fecha": "Fecha", "producto_nombre": "Producto", "cantidad_vendida": "Cant.", "precio_venta": "P. Unit."})
    assert any("EE.UU." in warning for warning in sample["warnings"])
    assert all(row["problem"] for row in sample["rows"])


def test_tabla_y_vista_previa_tratan_igual_guiones_y_porcentajes(fuente):
    _, source, _ = fuente
    source.write_text("Fecha;Producto;Cant.;P. Unit.;Desc;Costo\n10/09/2026;Coca;3;2.450;-;-\n11/09/2026;Yerba;1;3.200;10%;1.500\n", encoding="utf-8")
    mapping = {"fecha": "Fecha", "producto_nombre": "Producto", "cantidad_vendida": "Cant.", "precio_venta": "P. Unit.",
               "descuento": "Desc", "costo_unitario": "Costo"}
    sample = interpret_sample(source, mapping, discount="percentage")
    assert not any(row["problem"] for row in sample["rows"])
    preview = preview_source(source, mapping, price="gross_before_discount", discount="percentage")
    assert Decimal(preview["totals"]["ventas_netas"]) == Decimal("7350") + Decimal("2880")
    sample = interpret_sample(source, mapping, discount="per_line")
    assert sample["rows"][1]["problem"] and "%" in sample["rows"][1]["cells"][sample["fields"].index("descuento")]
