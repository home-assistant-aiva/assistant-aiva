"""The independent inventory photo keeps zero, dates and current values apart from sales."""

import csv

from aiva_collector.config import CollectorConfig
from aiva_collector.inventory import build_inventory


def test_inventory_builder_keeps_independent_field_dates_and_zero(tmp_path):
    path = tmp_path / "export.csv"
    headers = ["Fecha", "Código", "Producto", "Cantidad", "Precio", "Costo", "Stock",
               "Fecha Stock", "Fecha Costo", "Precio Actual", "Fecha Precio"]
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=headers, delimiter=";")
        writer.writeheader()
        writer.writerow(dict(zip(headers, ["01/07/2026", "A", "Artículo A", "1", "20", "10", "0",
                                           "17/10/2026", "16/10/2026", "30", "15/10/2026"])))
    mapping = {"fecha":"Fecha", "producto_codigo":"Código", "producto_nombre":"Producto",
               "cantidad_vendida":"Cantidad", "precio_venta":"Precio", "costo_unitario":"Costo",
               "stock_actual":"Stock", "fecha_stock":"Fecha Stock", "fecha_costo":"Fecha Costo",
               "precio_actual":"Precio Actual", "fecha_precio":"Fecha Precio"}
    config = CollectorConfig({"commerce_id":"fictional", "collector_id":"collector_fictional"},tmp_path/"config.json")
    setup = {"source_id":"source_fictional", "mapping":mapping,
             "profile":{"cost_basis":"current", "reader":{}}}
    photo = build_inventory(config,setup,path)
    observations = {item["kind"]:item for item in photo["observations"]}
    assert observations["stock"]["value"] == "0"
    assert observations["stock"]["observed_on"] == "2026-10-17"
    assert observations["current_cost"]["observed_on"] == "2026-10-16"
    assert observations["current_price"]["observed_on"] == "2026-10-15"
    assert len(observations) == 3
