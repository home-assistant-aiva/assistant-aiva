"""Drive actual Tk widgets against a synthetic source; no network or real credentials."""
import hashlib
import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _close_root(root):
    """Cancela los timers de la app antes de cerrar: Tk comparte el bucle de
    eventos entre ventanas raiz y el segundo escenario los dispararia."""
    for job in root.tk.splitlist(root.tk.call("after", "info")):
        try:
            root.after_cancel(job)
        except Exception:
            pass
    root.destroy()


def main():
    import tkinter as tk
    from aiva_collector.desktop_app import CollectorApp
    from aiva_collector.source_dialog import SourceDialog
    from aiva_collector.config import load_config
    from aiva_collector.cli import main as cli_main
    from aiva_collector.token_store import save_token, load_token
    with tempfile.TemporaryDirectory(prefix="aiva-guided-ui-") as temporary:
        root_dir = Path(temporary)
        folder = root_dir / "input"
        folder.mkdir()
        source = folder / "synthetic.csv"
        source.write_text("fecha,producto_codigo,producto_nombre,cantidad_vendida,precio_venta,descuento,costo_unitario\n2026-09-01,A,Sintetico,2,100,10,40\n", encoding="utf-8")
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        config_path = root_dir / "config.windows.json"
        config = {"backend_url": "https://synthetic.invalid", "commerce_id": "ui-synthetic", "collector_id": "ui-collector", "collector_token_env": "AIVA_UI_TEST_TOKEN", "input_dir": str(folder), "stable_file_interval_seconds": 0}
        for key in ("processed_dir", "error_dir", "output_dir", "state_dir", "log_file"):
            config[key] = str(root_dir / key)
        config_path.write_text(json.dumps(config))
        env = {"AIVA_COLLECTOR_STANDARD_CONFIG": str(config_path), "AIVA_COLLECTOR_DATA_DIR": str(root_dir)}
        with patch.dict(os.environ, env), patch("aiva_collector.desktop_service.scheduled_task_installed", return_value=None):
            save_token(Path(config["state_dir"]), "synthetic-ui-token")
            assert load_token(Path(config["state_dir"])) == "synthetic-ui-token"
            # Test DPAPI without ever using a production token.
            root = tk.Tk()
            app = CollectorApp(root)
            root.update()
            try:
                dialog = SourceDialog(app)
                with patch("aiva_collector.source_dialog.filedialog.askopenfilename", return_value=str(source)), patch("aiva_collector.source_dialog.messagebox.showerror", side_effect=lambda title, message, **kw: (_ for _ in ()).throw(AssertionError(message))), patch("aiva_collector.source_dialog.messagebox.showinfo"):
                    dialog.choose()
                    dialog.price.set("Bruto: antes del descuento")
                    dialog.discount.set("Importe por unidad")
                    dialog.complete.set(True)
                    root.update()
                    dialog.calculate()
                    assert dialog.preview["totals"]["ventas_netas"] == "180.000000"
                    assert dialog.preview["totals"]["descuentos"] == "20.000000"
                    dialog.save()
                assert load_config(config_path).raw["source_profile"]
                sent = []
                with patch("aiva_collector.cli._backend_mapping", return_value=None), patch("aiva_collector.client.CollectorClient.post_mapping_candidate", return_value={}), patch("aiva_collector.client.CollectorClient.post_status", return_value={}), patch("aiva_collector.client.CollectorClient.send_summary", side_effect=lambda summary: sent.append(summary) or {"summary_id": "synthetic", "_http_status_code": 201}):
                    assert cli_main(["run-auto", "--config", str(config_path)]) == 0
                    assert cli_main(["run-auto", "--config", str(config_path)]) == 0
                assert len(sent) == 1
                assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
            finally:
                _close_root(root)
                logging.shutdown()
    argentine = _argentine_export_scenario()
    evidence = {"build_commit": os.environ.get("AIVA_BUILD_COMMIT"), "actual_tk_widgets": True, "preview_net": "180", "preview_discount": "20", "dpapi_roundtrip": sys.platform == "win32", "sent_count_after_two_syncs": 1, "source_preserved": True, "network_used": False, "physical_windows_test": False, "argentine_export": argentine}
    Path("dist").mkdir(exist_ok=True)
    Path("dist/windows-guided-ui-verification.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence))


def _argentine_export_scenario():
    """Exportacion real de kiosco: '$ 1.890,00', '2.450', sin codigo, fila TOTAL.

    RC8 leia esta semana de $501.760 como $501,76 o la rechazaba entera.
    """
    import tkinter as tk
    from decimal import Decimal
    from aiva_collector.desktop_app import CollectorApp
    from aiva_collector.source_dialog import SourceDialog
    from aiva_collector.config import load_config
    from aiva_collector.cli import main as cli_main
    from aiva_collector.token_store import save_token
    with tempfile.TemporaryDirectory(prefix="aiva-guided-ar-") as temporary:
        root_dir = Path(temporary)
        folder = root_dir / "input"
        folder.mkdir()
        source = folder / "ventas_semana.csv"
        lines = ["Fecha;Producto;Rubro;Cant.;P. Unit.;Importe"]
        expected = Decimal(0)
        for day in range(10, 17):
            lines.append(f"{day:02d}/09/2026;Coca-Cola 2.25L;Bebidas;12;$ 1.890,00;$ 22.680,00")
            lines.append(f"{day:02d}/09/2026;Alfajor Jorgito;Golosinas;20;2.450;49.000")
            expected += 12 * 1890 + 20 * 2450
        lines.append(";;;;;")
        lines.append("TOTAL;;;224;;$ 501.760,00")
        source.write_text("\n".join(lines) + "\n", encoding="utf-8")
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        config_path = root_dir / "config.windows.json"
        config = {"backend_url": "https://synthetic.invalid", "commerce_id": "ui-ar", "collector_id": "ui-ar-collector", "collector_token_env": "AIVA_UI_TEST_TOKEN", "input_dir": str(folder), "stable_file_interval_seconds": 0}
        for key in ("processed_dir", "error_dir", "output_dir", "state_dir", "log_file"):
            config[key] = str(root_dir / key)
        config_path.write_text(json.dumps(config))
        env = {"AIVA_COLLECTOR_STANDARD_CONFIG": str(config_path), "AIVA_COLLECTOR_DATA_DIR": str(root_dir)}
        with patch.dict(os.environ, env), patch("aiva_collector.desktop_service.scheduled_task_installed", return_value=None):
            save_token(Path(config["state_dir"]), "synthetic-ui-token")
            root = tk.Tk()
            app = CollectorApp(root)
            root.update()
            try:
                dialog = SourceDialog(app)
                with patch("aiva_collector.source_dialog.filedialog.askopenfilename", return_value=str(source)), patch("aiva_collector.source_dialog.messagebox.showerror", side_effect=lambda title, message, **kw: (_ for _ in ()).throw(AssertionError(message))), patch("aiva_collector.source_dialog.messagebox.showinfo"):
                    dialog.choose()
                    root.update()
                    chosen = dialog.selected_mapping()
                    assert chosen["fecha"] == "Fecha" and chosen["producto_nombre"] == "Producto", chosen
                    assert chosen["cantidad_vendida"] == "Cant." and chosen["precio_venta"] == "P. Unit.", chosen
                    assert not chosen["producto_codigo"], chosen
                    rows = [dialog.table.item(item, "values") for item in dialog.table.get_children()]
                    assert rows, "La tabla de interpretacion quedo vacia"
                    assert not dialog.table.tag_has("problem"), "La tabla marco filas validas como ilegibles"
                    price_index = 1 + dialog.sample["columns"].index("Precio unitario")
                    price_cells = [row[price_index] for row in rows]
                    assert any(cell.endswith("1.890") for cell in price_cells), price_cells
                    assert any(cell == "2.450" for cell in price_cells), price_cells
                    dialog.price.set("Neto: descuento ya incluido")
                    dialog.discount.set("Importe por unidad")
                    dialog.complete.set(True)
                    root.update()
                    dialog.calculate()
                    assert Decimal(dialog.preview["totals"]["ventas_netas"]) == expected, dialog.preview["totals"]
                    assert dialog.preview["products_without_code"] == 2
                    assert len(dialog.preview["skipped_total_rows"]) == 1
                    assert any(w.startswith("Control superado") for w in dialog.preview["warnings"]), dialog.preview["warnings"]
                    dialog.save()
                saved = load_config(config_path).raw
                assert saved["decimal_conventions"]["precio_venta"] == "comma", saved.get("decimal_conventions")
                sent = []
                with patch("aiva_collector.cli._backend_mapping", return_value=None), patch("aiva_collector.client.CollectorClient.post_mapping_candidate", return_value={}), patch("aiva_collector.client.CollectorClient.post_status", return_value={}), patch("aiva_collector.client.CollectorClient.send_summary", side_effect=lambda summary: sent.append(summary) or {"summary_id": "synthetic", "_http_status_code": 201}):
                    assert cli_main(["run-auto", "--config", str(config_path)]) == 0
                assert len(sent) == 1
                snapshot = sent[0]["daily_snapshot"]
                net = sum(Decimal(metric["net_revenue"]) for metric in snapshot["metrics"])
                assert net == expected, net
                assert len(snapshot["metrics"]) == 14
                assert {status["status"] for status in snapshot["coverage"]} == {"complete"}
                assert all(metric["product_code"].startswith("name_hash:") for metric in snapshot["metrics"])
                assert sent[0]["resumen_financiero"]["facturacion_total"] == float(expected)
                assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
            finally:
                _close_root(root)
                logging.shutdown()
    return {"expected_net": str(expected), "sent_net": str(net), "daily_observations": 14, "products_without_code": 2, "total_row_ignored": True, "source_preserved": True}


if __name__ == "__main__":
    main()
