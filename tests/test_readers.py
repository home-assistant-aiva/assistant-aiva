from pathlib import Path

import pytest

from aiva_collector.config import load_config
from aiva_collector.readers import discover_input_files, read_csv, read_xlsx


def test_read_csv_demo():
    config = load_config("configs/example_config.json")
    rows = read_csv(Path("samples/input/ventas_demo.csv"), config)
    assert len(rows) >= 5
    assert rows[0]["producto_codigo"] == "SKU-COCA-225"


def test_discover_input_files():
    config = load_config("configs/example_config.json")
    files = discover_input_files(config)
    assert any(path.name == "ventas_demo.csv" for path in files)


def test_read_xlsx_if_openpyxl_available(tmp_path):
    pytest.importorskip("openpyxl")
    from openpyxl import Workbook

    path = tmp_path / "demo.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append(["producto_nombre", "cantidad_vendida", "precio_venta"])
    ws.append(["Demo", 1, 10])
    wb.save(path)
    rows = read_xlsx(path)
    assert rows == [{"producto_nombre": "Demo", "cantidad_vendida": 1, "precio_venta": 10}]
