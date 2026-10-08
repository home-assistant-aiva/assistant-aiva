"""RC9: numeros argentinos, productos sin codigo y un solo parser."""
from decimal import Decimal
from pathlib import Path

import pytest

from aiva_collector.config import CollectorConfig
from aiva_collector.daily import build_daily, decimal_number, stable_product_code
from aiva_collector.normalizer import (
    count_problem_rows,
    describe_problems,
    is_total_row,
    normalize_rows,
    parse_date,
    parse_number,
)
from aiva_collector.numeric_format import (
    CONVENTION_COMMA,
    CONVENTION_DOT,
    analyze_column,
    canonical_decimal,
    format_ar,
    parse_decimal_with,
)
from aiva_collector.readers import read_csv, read_xlsx
from aiva_collector.summarizer import build_summary

MAPPING = {
    "fecha": "Fecha",
    "producto_codigo": "Codigo",
    "producto_nombre": "Producto",
    "categoria": "Rubro",
    "cantidad_vendida": "Cantidad",
    "precio_venta": "Precio",
    "costo_unitario": "Costo",
}


def _config(tmp_path, **extra):
    raw = {
        "backend_url": "http://127.0.0.1:9", "commerce_id": "c", "collector_id": "k",
        "input_dir": str(tmp_path), "state_dir": str(tmp_path / "s"),
        "source_schema_version": "2.0.0", "price_semantics": "final_net",
        "business_timezone": "America/Argentina/Buenos_Aires", "daily_snapshot_complete": True,
        "column_mapping": MAPPING, **extra,
    }
    return CollectorConfig(raw=raw, config_path=Path(tmp_path) / "c.json")


def _semana():
    rows, real = [], Decimal(0)
    for day in range(10, 17):
        rows.append({"Fecha": f"2026-09-{day}", "Codigo": "P001", "Producto": "Coca-Cola 2.25L", "Rubro": "Bebidas",
                     "Cantidad": "12", "Precio": "$ 1.890,00", "Costo": "1.200"})
        rows.append({"Fecha": f"2026-09-{day}", "Codigo": "", "Producto": "Alfajor Jorgito", "Rubro": "Golosinas",
                     "Cantidad": "20", "Precio": "2.450", "Costo": "1.500"})
        real += 12 * 1890 + 20 * 2450
    return rows, real


@pytest.mark.parametrize("text,expected", [
    ("1.890", Decimal("1890")),
    ("$ 2.450", Decimal("2450")),
    ("$ 1.890,00", Decimal("1890.00")),
    ("ARS 3.500", Decimal("3500")),
    ("12.500,75", Decimal("12500.75")),
    ("(1.200)", Decimal("-1200")),
    ("1.234.567", Decimal("1234567")),
    ("1,5", Decimal("1.5")),
    ("1,234.50", Decimal("1234.50")),
    ("1,5E+03", Decimal("1500")),
    ("1890 pesos", Decimal("1890")),
    ("0.500", Decimal("0.500")),
])
def test_valores_sueltos_como_los_escribe_un_comercio(text, expected):
    assert parse_decimal_with(text) == expected
    assert parse_number(text) == float(expected)


@pytest.mark.parametrize("text", ["U$S 1,890.00", "USD 10", "€ 5", "10%", ",", ".", "abc", "-"])
def test_lo_que_no_es_un_monto_en_pesos_no_se_lee(text):
    assert parse_decimal_with(text) is None


def test_porcentaje_solo_si_se_permite():
    assert parse_decimal_with("10%", allow_percent=True) == Decimal("10")


def test_descuento_con_guion_es_sin_descuento_y_con_porcentaje_mal_configurado_rechaza(tmp_path):
    from aiva_collector.errors import ValidationError
    mapping = {**MAPPING, "descuento": "Desc"}
    base = {"Fecha": "2026-09-10", "Codigo": "A", "Producto": "Coca", "Rubro": "B", "Cantidad": "3", "Precio": "2.450", "Costo": "-"}
    config = _config(tmp_path, column_mapping=mapping, discount_semantics="per_line")
    normalized = normalize_rows([{**base, "Desc": "-"}], config)
    assert len(normalized.rows) == 1 and normalized.rows[0]["_daily_decimal"]["descuento"] is None
    assert normalized.rows[0]["costo_estado"] == "missing"
    with pytest.raises(ValidationError, match="Fila 1, columna 'Desc': el descuento tiene %"):
        normalize_rows([{**base, "Desc": "10%"}], config)
    with pytest.raises(ValidationError, match="otra moneda"):
        normalize_rows([{**base, "Desc": "USD 10"}], config)
    percent = _config(tmp_path, column_mapping=mapping, discount_semantics="percentage", price_semantics="gross_before_discount")
    assert normalize_rows([{**base, "Desc": "10%"}], percent).rows[0]["_daily_decimal"]["descuento"] == "10"


def test_la_convencion_se_decide_mirando_la_columna_entera():
    assert analyze_column(["1.890", "12,50"]).convention == CONVENTION_COMMA
    assert analyze_column(["1.890", "12.50"]).convention == CONVENTION_DOT
    profile = analyze_column(["1.890", "2.450"])
    assert profile.convention == CONVENTION_COMMA and profile.ambiguous
    # En cantidades, una columna con solo "2.450" es una balanza (2,45 kg).
    assert analyze_column(["2.450", "1.200"], ambiguous_default=CONVENTION_DOT).convention == CONVENTION_DOT


def test_canonical_no_reinterpreta_valores_ya_normalizados():
    # 2,450 kg ya normalizado es "2.450": releerlo con reglas argentinas daria 2450.
    assert canonical_decimal("2.450") == Decimal("2.450")
    assert canonical_decimal(1890.5) == Decimal("1890.5")
    assert canonical_decimal("abc") is None


def test_formato_argentino_para_mostrar():
    assert format_ar(Decimal("1890")) == "1.890"
    assert format_ar(Decimal("1.89")) == "1,89"
    assert format_ar(Decimal("501760.00")) == "501.760"
    assert format_ar(Decimal("-1234.5")) == "-1.234,5"


def test_sin_configurar_el_detalle_diario_solo_lleva_productos_con_codigo(tmp_path):
    """Sincronizacion automatica sin configurar: el payload no cambia respecto de RC8."""
    rows, real = _semana()
    config = _config(tmp_path, daily_snapshot_complete=False)
    summary = build_summary(normalize_rows(rows, config).rows, config, 1, 14, 0)
    assert summary["resumen_financiero"]["facturacion_total"] == float(real)
    assert {m["product_code"] for m in summary["daily_snapshot"]["metrics"]} == {"P001"}
    assert {item["status"] for item in summary["daily_snapshot"]["coverage"]} == {"unknown"}


def test_semana_de_kiosco_resumen_y_detalle_coinciden_con_la_realidad(tmp_path):
    rows, real = _semana()
    config = _config(tmp_path, source_profile={"context": "x", "headers": [], "suffix": ".csv"})
    normalized = normalize_rows(rows, config)
    assert len(normalized.rows) == 14 and not normalized.discarded
    summary = build_summary(normalized.rows, config, 1, 14, 0)
    assert summary["resumen_financiero"]["facturacion_total"] == float(real)
    snapshot = summary["daily_snapshot"]
    assert sum(Decimal(m["net_revenue"]) for m in snapshot["metrics"]) == real
    assert len(snapshot["metrics"]) == 14
    assert {item["status"] for item in snapshot["coverage"]} == {"complete"}
    codes = {m["product_code"] for m in snapshot["metrics"]}
    assert "P001" in codes and any(code.startswith("name_hash:") for code in codes)


def test_kilos_con_tres_decimales_no_se_multiplican_por_mil_en_el_detalle(tmp_path):
    rows = [{"Fecha": "2026-09-10", "Codigo": "Q1", "Producto": "Queso", "Rubro": "Fiambres",
             "Cantidad": "2,450", "Precio": "8.900,00", "Costo": ""}]
    config = _config(tmp_path)
    normalized = normalize_rows(rows, config)
    metric = build_summary(normalized.rows, config, 1, 1, 0)["daily_snapshot"]["metrics"][0]
    assert Decimal(metric["quantity"]) == Decimal("2.45")
    assert Decimal(metric["net_revenue"]) == Decimal("21805")


def test_formato_congelado_por_campo_gana_a_la_deteccion(tmp_path):
    rows = [{"Fecha": "2026-09-10", "Codigo": "A", "Producto": "X", "Rubro": "R", "Cantidad": "1", "Precio": "1.890", "Costo": ""}]
    config = _config(tmp_path, decimal_conventions={"precio_venta": "dot"})
    assert normalize_rows(rows, config).rows[0]["precio_venta"] == 1.89


def test_codigo_estable_sin_codigo_de_barras():
    a = stable_product_code({"producto_nombre": "Alfajor  Jorgito", "categoria": "Golosinas"})
    b = stable_product_code({"producto_nombre": "alfajor jorgito", "categoria": "GOLOSINAS"})
    c = stable_product_code({"producto_nombre": "Alfajor Jorgito", "categoria": "Kiosco"})
    assert a == b and a.startswith("name_hash:") and a != c
    assert stable_product_code({"producto_codigo": " 779 ", "producto_nombre": "x"}) == "779"
    assert stable_product_code({"producto_nombre": ""}) is None


def test_decimal_number_externo_usa_el_mismo_parser():
    assert decimal_number("$ 1.890,00") == Decimal("1890.00")
    assert decimal_number("2.450") == Decimal("2450")


def test_filas_malas_dicen_fila_columna_y_valor(tmp_path):
    rows = [
        {"Fecha": "2026-09-10", "Codigo": "A", "Producto": "Coca", "Rubro": "B", "Cantidad": "2", "Precio": "abc", "Costo": ""},
        {"Fecha": "31/02/2026", "Codigo": "B", "Producto": "Yerba", "Rubro": "A", "Cantidad": "1", "Precio": "3.200", "Costo": ""},
    ]
    normalized = normalize_rows(rows, _config(tmp_path))
    assert count_problem_rows(normalized, require_dates=True) == 2
    lines = describe_problems(normalized, require_dates=True)
    assert "Fila 1, columna 'Precio' = 'abc'" in lines[0]
    assert "Fila 2, columna 'Fecha' = '31/02/2026'" in lines[1]


@pytest.mark.parametrize("label", ["TOTAL", "Totales", "Total general", "Total ventas", "Total del día", "TOTAL $", "Subtotal:"])
def test_fila_de_total_al_pie_no_es_una_venta(tmp_path, label):
    rows, _ = _semana()
    rows.append({"Fecha": label, "Codigo": "", "Producto": "", "Rubro": "", "Cantidad": "224", "Precio": "", "Costo": ""})
    normalized = normalize_rows(rows, _config(tmp_path))
    assert not normalized.discarded and normalized.skipped_total_rows == [15]


@pytest.mark.parametrize("product", ["Total Petrolero", "Totalín", "Total Café 250g"])
def test_productos_que_empiezan_con_total_son_ventas(product):
    assert not is_total_row({"Fecha": "2026-09-10", "Producto": product}, MAPPING)
    assert not is_total_row({"Fecha": "", "Producto": product}, MAPPING)


@pytest.mark.parametrize("value,expected", [
    ("10/09/2026", "2026-09-10"),
    ("10/09/26", "2026-09-10"),
    ("2026-09-10 14:35:00", "2026-09-10"),
    ("10/09/2026 14:35", "2026-09-10"),
    ("10.09.2026", "2026-09-10"),
    (46275, "2026-09-10"),
    ("46275", "2026-09-10"),
])
def test_fechas_que_exporta_un_sistema_argentino(value, expected):
    assert parse_date(value).isoformat() == expected


def test_fecha_estilo_eeuu_no_se_invierte_en_silencio():
    assert parse_date("09/25/2026") is None


def test_csv_ignora_filas_vacias_y_conserva_el_numero_de_fila(tmp_path):
    path = tmp_path / "v.csv"
    path.write_text("Fecha;Producto;Cantidad;Precio\n2026-09-10;Coca;1;1.890\n;;;\n2026-09-11;Yerba;1;abc\n", encoding="utf-8")
    rows = read_csv(path, CollectorConfig(raw={"encoding": "utf-8"}, config_path=tmp_path / "c.json"))
    assert len(rows) == 2 and rows.row_numbers == [2, 4]
    config = _config(tmp_path, column_mapping={"fecha": "Fecha", "producto_nombre": "Producto", "cantidad_vendida": "Cantidad", "precio_venta": "Precio"})
    normalized = normalize_rows(rows, config)
    assert describe_problems(normalized)[0].startswith("Fila 4, columna 'Precio'")


def test_xlsx_numero_de_fila_con_titulo_arriba(tmp_path):
    from openpyxl import Workbook
    book = Workbook()
    sheet = book.active
    sheet.append(["Reporte de ventas"])
    sheet.append(["Fecha", "Producto", "Cantidad", "Precio"])
    sheet.append(["2026-09-10", "Coca", 1, "1.890"])
    sheet.append([None, None, None, None])
    sheet.append(["2026-09-11", "Yerba", 1, "3.200"])
    path = tmp_path / "v.xlsx"
    book.save(path)
    rows = read_xlsx(path, CollectorConfig(raw={}, config_path=tmp_path / "c.json"))
    assert rows.row_numbers == [3, 5]
