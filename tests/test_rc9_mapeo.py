"""RC9: autodeteccion de columnas con abreviaturas y valores."""
import pytest

from aiva_collector.column_mapping import detect_column_mapping

CASOS = [
    (["Fecha", "Producto", "Cantidad", "Precio", "Costo"],
     {"fecha": "Fecha", "producto_nombre": "Producto", "cantidad_vendida": "Cantidad", "precio_venta": "Precio", "costo_unitario": "Costo"}),
    (["Fecha", "Comprobante", "Articulo", "Descripcion", "Cantidad", "Precio Unitario", "Importe"],
     {"fecha": "Fecha", "producto_codigo": "Articulo", "producto_nombre": "Descripcion", "cantidad_vendida": "Cantidad", "precio_venta": "Precio Unitario"}),
    (["FECHA", "COD. BARRA", "DETALLE", "CANT.", "P. UNIT.", "SUBTOTAL"],
     {"fecha": "FECHA", "producto_codigo": "COD. BARRA", "producto_nombre": "DETALLE", "cantidad_vendida": "CANT.", "precio_venta": "P. UNIT."}),
    (["Fec.", "Cód. Art.", "Denominación", "Un.", "P/U"],
     {"fecha": "Fec.", "producto_codigo": "Cód. Art.", "producto_nombre": "Denominación", "cantidad_vendida": "Un.", "precio_venta": "P/U"}),
    (["F. Venta", "Concepto", "Cdad", "$ Unit"],
     {"fecha": "F. Venta", "producto_nombre": "Concepto", "cantidad_vendida": "Cdad", "precio_venta": "$ Unit"}),
    (["Fecha", "Codigo", "Producto", "Cantidad", "Precio Unitario", "Precio Total", "Cantidad en Stock"],
     {"fecha": "Fecha", "producto_codigo": "Codigo", "producto_nombre": "Producto", "cantidad_vendida": "Cantidad", "precio_venta": "Precio Unitario", "stock_actual": "Cantidad en Stock"}),
]


@pytest.mark.parametrize("headers,expected", CASOS)
def test_planillas_argentinas_tipicas(headers, expected):
    result = detect_column_mapping(headers)
    for field, column in expected.items():
        assert result.mapping.get(field) == column, (field, result.mapping)


def test_precio_un_no_se_confunde_con_cantidad():
    result = detect_column_mapping(["Fecha", "Producto", "Cant.", "Precio Un."])
    assert result.mapping["cantidad_vendida"] == "Cant."
    assert result.mapping["precio_venta"] == "Precio Un."


def test_planilla_contable_no_se_aprueba():
    result = detect_column_mapping(["Fecha", "Cuenta", "Debe", "Haber", "Saldo"])
    assert result.status == "failed"


def test_desc_con_importes_es_descuento_y_con_nombres_es_producto():
    importes = [{"Fecha": "10/09/2026", "Articulo": "Coca 2.25", "Cant": "2", "Precio": "1.890,00", "Desc": "100"},
                {"Fecha": "11/09/2026", "Articulo": "Alfajor", "Cant": "3", "Precio": "2.450", "Desc": "0"},
                {"Fecha": "12/09/2026", "Articulo": "Yerba", "Cant": "1", "Precio": "3.200", "Desc": "50"}]
    guided = detect_column_mapping(list(importes[0]), importes, fill_from_values=True)
    assert guided.mapping["descuento"] == "Desc"
    assert guided.mapping["producto_nombre"] == "Articulo"
    # Sincronizacion automatica: sin tipo de descuento elegido, "Desc." no se toma
    # (como en RC8) para no rechazar el archivo por "descuento ambiguo".
    automatic = detect_column_mapping(list(importes[0]), importes)
    assert "descuento" not in automatic.mapping
    assert automatic.mapping["producto_nombre"] == "Articulo"
    nombres = [{"Fecha": "10/09/2026", "Desc": "Coca 2.25", "Cant": "2", "Precio": "1890"},
               {"Fecha": "11/09/2026", "Desc": "Alfajor", "Cant": "3", "Precio": "2450"}]
    assert detect_column_mapping(list(nombres[0]), nombres).mapping["producto_nombre"] == "Desc"


def test_articulo_con_codigos_va_a_codigo():
    rows = [{"Fecha": "10/09/2026", "Articulo": "00123", "Descripcion": "Coca 2.25", "Cant": "2", "Precio": "1890"}] * 3
    result = detect_column_mapping(list(rows[0]), rows)
    assert result.mapping["producto_codigo"] == "Articulo"
    assert result.mapping["producto_nombre"] == "Descripcion"


def test_dia_de_la_semana_no_es_la_fecha():
    rows = [{"Dia": "Lunes", "Fecha venta": "10/09/2026", "Producto": "Coca", "Cantidad": "2", "Precio": "1890"}] * 3
    assert detect_column_mapping(list(rows[0]), rows).mapping["fecha"] == "Fecha venta"


def test_fecha_sin_nombre_solo_en_la_configuracion_guiada():
    rows = [{"Columna1": f"1{day}/09/2026", "Producto": "Coca", "Cantidad": "2", "Precio": "1890"} for day in range(3)]
    assert "fecha" not in detect_column_mapping(list(rows[0]), rows).mapping
    guided = detect_column_mapping(list(rows[0]), rows, fill_from_values=True)
    assert guided.mapping["fecha"] == "Columna1"
    assert guided.scores["fecha"] < 0.85


def _rows(headers, data):
    return [dict(zip(headers, values)) for values in data]


@pytest.mark.parametrize("headers,field,expected", [
    (["Fecha", "Producto", "Kg", "Cantidad", "Precio"], "cantidad_vendida", "Cantidad"),
    (["Fecha", "Producto", "Uds", "Cantidad", "Precio"], "cantidad_vendida", "Cantidad"),
    (["Fecha", "Comprobante", "Concepto", "Producto", "Cantidad", "Precio"], "producto_nombre", "Producto"),
    (["Fecha", "Producto", "Cantidad", "Valor", "P. Unit."], "precio_venta", "P. Unit."),
    (["Fecha", "Producto", "Cantidad", "Unitario", "Precio"], "precio_venta", "Precio"),
    (["Date", "Item", "Qty Sold", "Price"], "cantidad_vendida", "Qty Sold"),
])
def test_los_alias_nuevos_nunca_le_ganan_a_los_de_siempre(headers, field, expected):
    assert detect_column_mapping(headers).mapping.get(field) == expected


def test_tipo_de_comprobante_no_es_categoria():
    headers = ["Fecha", "Producto", "Tipo de comprobante", "Linea", "Cantidad", "Precio"]
    rows = _rows(headers, [["10/09/2026", "Coca", "Ticket", "Bebidas", "3", "1890"]] * 3)
    assert detect_column_mapping(headers, rows).mapping.get("categoria") == "Linea"


TICKETS = [["10/09/2026", "T-0001", "Yerba", "3", "1890"], ["10/09/2026", "T-0001", "Azucar", "2", "990"],
           ["10/09/2026", "T-0002", "Yerba", "1", "1890"], ["10/09/2026", "T-0003", "Coca", "1", "1890"],
           ["10/09/2026", "T-0003", "Azucar", "1", "990"]]


def test_numero_de_ticket_no_se_usa_como_codigo_de_producto():
    headers = ["Fecha", "Ref", "Producto", "Cantidad", "Precio"]
    assert "producto_codigo" not in detect_column_mapping(headers, _rows(headers, TICKETS)).mapping
    # Un alias nuevo ('Art') con valores que no identifican productos tampoco.
    headers = ["Fecha", "Art", "Producto", "Cantidad", "Precio"]
    result = detect_column_mapping(headers, _rows(headers, TICKETS))
    assert "producto_codigo" not in result.mapping
    assert any("no identifica productos" in warning for warning in result.warnings)


def test_codigo_generico_varios_no_hace_perder_la_columna_codigo():
    headers = ["Fecha", "Codigo", "Producto", "Cantidad", "Precio"]
    rows = _rows(headers, [["10/09/2026", "7790001", "Yerba", "1", "1890"], ["10/09/2026", "999", "Pan", "1", "500"],
                           ["10/09/2026", "999", "Facturas", "3", "300"], ["10/09/2026", "7790002", "Coca", "1", "1890"]])
    assert detect_column_mapping(headers, rows).mapping["producto_codigo"] == "Codigo"


def test_fechas_como_numero_de_serie_o_aaaammdd_siguen_mapeadas():
    headers = ["Fecha", "Producto", "Cantidad", "Precio"]
    assert detect_column_mapping(headers, _rows(headers, [[46275, "Coca", 3, 1890], [46276, "Yerba", 2, 3200]])).mapping["fecha"] == "Fecha"
    assert detect_column_mapping(headers, _rows(headers, [["20260910", "Coca", "3", "1890"]] * 3)).mapping["fecha"] == "Fecha"


def test_xlsx_elige_la_hoja_de_ventas_aunque_otra_tenga_mas_columnas_conocidas(tmp_path):
    from openpyxl import Workbook
    from aiva_collector.config import CollectorConfig
    from aiva_collector.readers import read_xlsx
    book = Workbook()
    ventas = book.active
    ventas.title = "Ventas"
    ventas.append(["Fecha", "Producto", "Cantidad", "Precio", "Total"])
    ventas.append(["2026-09-10", "Coca", 3, 1890, 5670])
    stock = book.create_sheet("Stock")
    stock.append(["Cod", "Art", "Rubro", "Tipo", "Stock", "Valor", "Costo"])
    stock.append(["1", "Coca", "Bebidas", "A", 10, 1890, 1200])
    book.save(tmp_path / "libro.xlsx")
    rows = read_xlsx(tmp_path / "libro.xlsx", CollectorConfig(raw={}, config_path=tmp_path / "c.json"))
    assert list(rows[0]) == ["Fecha", "Producto", "Cantidad", "Precio", "Total"]


def test_mapeo_aprobado_sin_codigo_se_respeta_si_el_archivo_no_tiene_codigo(tmp_path):
    """Regla de RC8: solo se reemplaza un mapeo aprobado si la deteccion encuentra
    fecha y codigo que el mapeo omite. Un 'Ref' con numeros de ticket no es codigo."""
    from pathlib import Path
    from aiva_collector.cli import _resolve_mapping_for_rows
    from aiva_collector.config import CollectorConfig
    headers = ["Fecha", "Ref", "Producto", "Cantidad", "Precio"]
    rows = _rows(headers, TICKETS)
    approved = {"fecha": "Fecha", "producto_nombre": "Producto", "cantidad_vendida": "Cantidad", "precio_venta": "Precio"}
    config = CollectorConfig(raw={"column_mapping": approved}, config_path=Path(tmp_path) / "c.json")
    effective, _ = _resolve_mapping_for_rows(config, rows, backend_mapping=None)
    assert effective.column_mapping == approved
