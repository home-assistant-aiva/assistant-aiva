from aiva_collector.config import load_config
from aiva_collector.normalizer import normalize_rows, parse_number


def test_parse_number_comma_and_point():
    assert parse_number("1,5") == 1.5
    assert parse_number("1.234,50") == 1234.5
    assert parse_number("1,234.50") == 1234.5


def test_product_without_code_is_valid():
    config = load_config("configs/example_config.json")
    result = normalize_rows(
        [
            {
                "producto_nombre": "Galletitas X",
                "cantidad_vendida": "1",
                "precio_venta": "1200",
                "categoria": "Almacen",
                "producto_codigo": "",
            }
        ],
        config,
    )
    assert len(result.rows) == 1
    assert result.rows[0]["producto_codigo"] is None


def test_discard_incomplete_rows():
    config = load_config("configs/example_config.json")
    result = normalize_rows([{"producto_nombre": "", "cantidad_vendida": "", "precio_venta": "10"}], config)
    assert result.rows == []
    assert result.discarded[0]["reasons"]
