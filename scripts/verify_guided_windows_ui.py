"""Drive actual Tk widgets against a synthetic source; no network or real credentials."""
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


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
                root.destroy()
    evidence = {"build_commit": os.environ.get("AIVA_BUILD_COMMIT"), "actual_tk_widgets": True, "preview_net": "180", "preview_discount": "20", "dpapi_roundtrip": sys.platform == "win32", "sent_count_after_two_syncs": 1, "source_preserved": True, "network_used": False, "physical_windows_test": False}
    Path("dist").mkdir(exist_ok=True)
    Path("dist/windows-guided-ui-verification.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence))


if __name__ == "__main__":
    main()
