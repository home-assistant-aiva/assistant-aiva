from aiva_collector.config import load_config
from aiva_collector.normalizer import normalize_rows
from aiva_collector.summarizer import build_summary, idempotency_key


def _summary():
    config = load_config("configs/example_config.json")
    rows = [
        {
            "fecha": "2026-06-01",
            "producto_codigo": "A",
            "producto_nombre": "Producto A",
            "categoria": "Cat",
            "cantidad_vendida": "2",
            "precio_venta": "100",
            "costo_unitario": "60",
            "stock_actual": "5",
        },
        {
            "fecha": "2026-06-02",
            "producto_codigo": "A",
            "producto_nombre": "Producto A",
            "categoria": "Cat",
            "cantidad_vendida": "3",
            "precio_venta": "120",
            "costo_unitario": "70",
            "stock_actual": "4",
        },
    ]
    normalized = normalize_rows(rows, config)
    return build_summary(normalized.rows, config, 1, 2, 0)


def test_financial_summary():
    summary = _summary()
    product = summary["productos_resumidos"][0]
    assert product["cantidad_vendida"] == 5
    assert product["facturacion_total"] == 560
    assert product["costo_total_estimado"] == 330
    assert summary["resumen_financiero"]["margen_bruto_estimado"] == 230


def test_missing_cost_keeps_margin_fields_null():
    config = load_config("configs/example_config.json")
    normalized = normalize_rows(
        [
            {
                "fecha": "2026-06-01",
                "producto_nombre": "Sin costo",
                "cantidad_vendida": "2",
                "precio_venta": "100",
                "costo_unitario": "",
                "stock_actual": "5",
            }
        ],
        config,
    )
    summary = build_summary(normalized.rows, config, 1, 1, 0)
    product = summary["productos_resumidos"][0]
    assert product["costo_unitario_promedio"] is None
    assert product["costo_total_estimado"] is None
    assert product["margen_bruto_estimado"] is None
    assert product["margen_porcentaje_estimado"] is None
    assert product["costo_estado"] == "missing"
    assert summary["resumen_financiero"]["productos_sin_costo"] == 1


def test_idempotency_key_is_stable():
    assert idempotency_key(_summary()) == idempotency_key(_summary())
