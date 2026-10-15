"""Real Tk, SQLite reader, DPAPI and frozen foreground/background credential access.

Synthetic fixtures only. This does not certify a physical PC or SQL Server.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cli')
    parser.add_argument('--background')
    args = parser.parse_args()
    if sys.platform != 'win32':
        raise SystemExit('Windows runner required')
    import tkinter as tk
    from aiva_collector.connection_wizard import ConnectionWizard
    from aiva_collector.connection_setup import activate
    from aiva_collector.source_credentials import CredentialVault
    from aiva_collector.config import load_config
    with tempfile.TemporaryDirectory(prefix='aiva-connection-windows-') as temporary:
        root_dir = Path(temporary)
        source = root_dir/'ventas.csv'
        from datetime import date, timedelta
        day = str(date.today()-timedelta(days=1))
        source.write_text('Fecha;Producto;Cantidad;Precio\n'+day+';Producto sintético;2;1.890,00\n', encoding='utf-8')
        original = hashlib.sha256(source.read_bytes()).hexdigest()
        cfg_path = root_dir/'config.json'
        cfg_path.write_text(json.dumps({'commerce_id':'synthetic-connection','collector_id':'synthetic-reader',
            'backend_url':'https://synthetic.invalid','collector_token_env':'AIVA_CONNECTION_TEST',
            'input_dir':str(root_dir),'state_dir':str(root_dir/'state')}))
        os.environ['AIVA_COLLECTOR_STANDARD_CONFIG']=str(cfg_path)
        config = load_config(cfg_path)
        root = tk.Tk()
        root.geometry('1366x768')
        wizard = ConnectionWizard(root)
        wizard.vars['source_path'].set(str(source))
        wizard.complete.set(True)
        wizard.test_access()
        deadline=time.monotonic()+15
        while wizard.busy and time.monotonic()<deadline:
            root.update()
            time.sleep(.02)
        assert wizard.sample, wizard.status.get()
        assert wizard.mapping['precio_venta'].get()=='Precio'
        wizard.preview()
        assert wizard.reviewed, wizard.status.get()
        assert '1890' in json.dumps(wizard.reviewed['examples'])
        wizard.save_progress()
        setup = activate(config, wizard.reviewed)
        vault = CredentialVault(config, setup['source_id'])
        vault.store({'access_token':'synthetic-windows-credential'})
        assert vault.load()['access_token']=='synthetic-windows-credential'
        assert b'synthetic-windows-credential' not in vault.path.read_bytes()
        for program in (args.cli, args.background):
            if program:
                child_env = {**os.environ, 'ProgramData':str(root_dir/'programdata')}
                result=subprocess.run([program,'connection-credential-check','--config',str(cfg_path)], env=child_env,
                    capture_output=True, timeout=30)
                assert result.returncode==0, 'Frozen process could not open protected source credentials'
        if args.cli:
            result=subprocess.run([args.cli,'connection-driver-info'], capture_output=True, timeout=30)
            assert result.returncode==0, 'pyodbc unavailable in frozen candidate'
        assert hashlib.sha256(source.read_bytes()).hexdigest()==original
        wizard.destroy()
        root.destroy()
        evidence={'actual_tk_widgets':True,'source_preserved':True,'dpapi_source_roundtrip':True,
            'frozen_interactive_access':bool(args.cli),'frozen_background_access':bool(args.background),
            'history_selector':True,'physical_windows_test':False,'sqlserver_integration':False,
            'build_commit':os.environ.get('AIVA_BUILD_COMMIT')}
        Path('dist').mkdir(exist_ok=True)
        Path('dist/windows-connection-verification.json').write_text(json.dumps(evidence,indent=2))
        print(json.dumps(evidence))


if __name__=='__main__':
    main()
