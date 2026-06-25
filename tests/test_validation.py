from aiva_collector.validation import validate_normalized_data


def test_missing_required_columns_blocks():
    result = validate_normalized_data(raw_rows=[{"producto": "A"}], mapping={}, normalized_rows=[], discarded_rows=[])

    assert not result.is_valid
    assert any("Faltan columnas requeridas" in item for item in result.blocking_errors)


def test_empty_price_row_is_invalid_and_no_valid_rows_blocks():
    result = validate_normalized_data(
        raw_rows=[{"producto": "A", "cantidad": "1", "precio": ""}],
        mapping={"producto_nombre": "producto", "cantidad_vendida": "cantidad", "precio_venta": "precio"},
        normalized_rows=[],
        discarded_rows=[{"row_number": 1, "reasons": ["precio_venta requerido"]}],
    )

    assert not result.is_valid
    assert result.rows_invalid == 1


def test_missing_cost_stock_and_negative_stock_warn():
    result = validate_normalized_data(
        raw_rows=[{"producto": "A"}],
        mapping={"producto_nombre": "producto", "cantidad_vendida": "cantidad", "precio_venta": "precio"},
        normalized_rows=[
            {
                "producto_nombre": "A",
                "producto_codigo": None,
                "cantidad_vendida": 1,
                "precio_venta": 10,
                "costo_unitario": None,
                "stock_actual": -1,
                "fecha": None,
            }
        ],
        discarded_rows=[],
    )

    assert result.is_valid
    assert any("sin costo" in warning for warning in result.warnings)
    assert any("stock negativo" in warning for warning in result.warnings)


def test_invalid_samples_are_limited():
    result = validate_normalized_data(
        raw_rows=[{"producto": ""}] * 10,
        mapping={"producto_nombre": "producto", "cantidad_vendida": "cantidad", "precio_venta": "precio"},
        normalized_rows=[],
        discarded_rows=[{"row_number": i, "reasons": ["producto vacio"]} for i in range(10)],
    )

    assert len(result.invalid_samples) == 5
