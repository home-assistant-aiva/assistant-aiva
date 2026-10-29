from datetime import date

from aiva_collector.config import CollectorConfig
from aiva_collector.normalizer import normalize_rows
from aiva_collector.summarizer import build_summary
from aiva_collector.column_mapping import detect_column_mapping


def test_last_sale_uses_accredited_date_and_unknown_is_not_zero(tmp_path):
    mapping={"fecha":"Fecha", "producto_codigo":"Código", "producto_nombre":"Producto",
             "cantidad_vendida":"Cantidad", "precio_venta":"Precio", "stock_actual":"Stock",
             "fecha_ultima_venta":"Últ. Venta"}
    config=CollectorConfig({"commerce_id":"fictional", "collector_id":"collector_fictional",
        "column_mapping":mapping,"source_schema_version":"1.0.0"},tmp_path/"config.json")
    raw=[{"Fecha":"17/10/2026","Código":"A","Producto":"Con venta vieja",
          "Cantidad":"0","Precio":"20","Stock":"4","Últ. Venta":"27/02/2026"},
         {"Fecha":"17/10/2026","Código":"B","Producto":"Sin historia",
          "Cantidad":"0","Precio":"20","Stock":"4","Últ. Venta":""},
         {"Fecha":"17/10/2026","Código":"C","Producto":"Venta acreditada",
          "Cantidad":"1","Precio":"20","Stock":"4","Últ. Venta":"27/02/2026"}]
    normalized=normalize_rows(raw,config)
    summary=build_summary(normalized.rows,config,1,3,0)
    products={item['producto_codigo']:item for item in summary['productos_resumidos']}
    assert products['A']['dias_sin_ventas']==(date(2026,10,17)-date(2026,2,27)).days
    assert products['B']['dias_sin_ventas'] is None
    assert products['C']['dias_sin_ventas'] == 0


def test_v2_headers_keep_last_sale_distinct_from_inventory_dates():
    headers = ['Fecha', 'Código', 'Descripción', 'Cantidad', 'Precio Unit.',
               'Costo Unit.', 'Precio Venta Actual', 'Existencia',
               'Fecha Existencia', 'Fecha Costo y Precio', 'Últ. Venta']
    mapping = detect_column_mapping(headers).mapping
    assert mapping['fecha_ultima_venta'] == 'Últ. Venta'
    assert mapping['fecha_stock'] == 'Fecha Existencia'
    assert mapping['fecha_valores_actuales'] == 'Fecha Costo y Precio'
    assert mapping['precio_actual'] == 'Precio Venta Actual'
