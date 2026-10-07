"""Offline RC7 pilot verification. No network, ingestion or messaging operations."""
from __future__ import annotations

import csv
import ctypes
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import xml.etree.ElementTree as ET

from aiva_collector.config import CollectorConfig
from aiva_collector.config_discovery import resolve_runtime_config
from aiva_collector.cli import _resolve_mapping_for_rows
from aiva_collector.normalizer import parse_date
from aiva_collector.daily import decimal_number
from aiva_collector.readers import read_file
from aiva_collector.version import VERSION

EXPECTED_SHA = '100e40e624f47297b1ed3e992ea85970dc18da2fe7e8ed9e302f677480d9e597'
CLI_SHA = 'edaf6f67b9cf01f2173db4127120591bbdcf07f3876373bde990d62a53904d9e'
COMMERCE = 'commerce_a0e93d3ec7ac'
COLLECTOR = 'collector_dc15555b7052'
TASK = 'AIVA Collector Auto'

class Stop(Exception):
    """A safe error suitable for the operator and diagnostic."""

def require(ok, message):
    if not ok:
        raise Stop(message)

def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def run(args):
    result = subprocess.run(args, capture_output=True, timeout=60, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    require(result.returncode == 0, 'No se pudo completar una comprobacion de Windows.')
    raw = result.stdout
    return raw.decode('utf-16' if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8', errors='replace')

def task_xml():
    return run(['schtasks.exe', '/Query', '/TN', TASK, '/XML'])

def task_disabled():
    doc = ET.fromstring(task_xml())
    ns = {'t': 'http://schemas.microsoft.com/windows/2004/02/mit/task'}
    return doc.findtext('t:Settings/t:Enabled', namespaces=ns) == 'false'

def no_processes():
    watched = {'aiva-collector.exe', 'aiva-collector-cli.exe', 'aiva-collector-background.exe'}
    rows = csv.reader(io.StringIO(run(['tasklist.exe', '/FO', 'CSV', '/NH'])))
    return not any(row and row[0].lower() in watched for row in rows)

def ro(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)

def local_state(db, config, source):
    with closing(ro(db)) as conn:
        conn.row_factory = sqlite3.Row
        columns = {r[1] for r in conn.execute('PRAGMA table_info(processed_files)')}
        schema = "COALESCE(source_schema_version,'1.0.0')" if 'source_schema_version' in columns else "'1.0.0'"
        rows = conn.execute(f'''SELECT status, {schema} schema_version, backend_summary_id,
            file_path FROM processed_files WHERE file_sha256=? AND commerce_id=? AND collector_id=?
            AND (backend_url=? OR backend_url IS NULL)''',
            (EXPECTED_SHA, config.commerce_id, config.collector_id, config.backend_url)).fetchall()
        result = {'queue_counts': dict(conn.execute('SELECT status,COUNT(*) FROM upload_queue GROUP BY status')),
                  'matching_sha_records': [{'status':r['status'], 'schema':r['schema_version'],
                      'summary_id':r['backend_summary_id'], 'same_path':Path(r['file_path']) == source} for r in rows]}
    return result

def backup(root, db, destination, xml):
    """Quiescent copy plus SQLite online backup, followed by restoration verification."""
    require(not destination.exists(), 'El destino del respaldo ya existe.')
    files = [p for p in root.rglob('*') if p.is_file()]
    require(not any(p.is_symlink() or bool(getattr(p.lstat(), 'st_file_attributes', 0) & 0x400)
                    for p in root.rglob('*')), 'Hay enlaces en el directorio; revisar respaldo.')
    # Caller creates a protected parent before any credentials are copied.
    destination.mkdir()
    excluded = {db, Path(str(db)+'-wal'), Path(str(db)+'-shm')}
    for src in files:
        if src in excluded:
            continue
        dst = destination / src.relative_to(root)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        require(sha(src) == sha(dst), 'El respaldo de un archivo no coincide.')
    target_db = destination / db.relative_to(root)
    target_db.parent.mkdir(parents=True, exist_ok=True)
    src_conn, dst_conn = ro(db), sqlite3.connect(target_db)
    try:
        src_conn.backup(dst_conn)
    finally:
        src_conn.close()
        dst_conn.close()
    with closing(ro(target_db)) as conn:
        require(conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'La base respaldada no pasa integridad.')
    (destination / 'scheduled-task-before.xml').write_text(xml, encoding='utf-8')
    # Restore remains under the same protected parent, never in a public temp folder.
    restored = destination.parent / 'restore-verified'
    shutil.copytree(destination, restored)
    copied = [p for p in destination.rglob('*') if p.is_file()]
    require(all(sha(p) == sha(restored / p.relative_to(destination)) for p in copied), 'Fallo la restauracion verificada.')
    with closing(ro(restored / db.relative_to(root))) as conn:
        require(conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'La base restaurada no pasa integridad.')
    return {'files_verified': len(copied), 'sqlite_integrity': 'ok', 'restore_integrity': 'ok', 'database_sha256': sha(target_db)}

def analyze(source, config):
    """Independent arithmetic over mapped Excel cells; does not certify price semantics."""
    raw = read_file(source, config)
    effective, mapping = _resolve_mapping_for_rows(config, raw)
    mp = effective.column_mapping
    result = {'rows_read': len(raw), 'mapping_status': mapping.status, 'mapping': mapping.mapping,
              'price_semantics_verified': False, 'synthetic_provenance_verified': False,
              'completeness_certified': False}
    required = {'fecha','producto_codigo','cantidad_vendida','precio_venta','costo_unitario'}
    if not required <= mp.keys():
        result['blocked'] = 'Falta mapping para fecha, codigo, cantidad, precio o costo.'
        return result
    days, pairs, codes, months = set(), [], set(), {}
    invalid, discount_nonzero, discount_missing, cost_missing = 0, 0, 0, 0
    for row in raw:
        day = parse_date(row.get(mp['fecha']), str(config.raw.get('date_format', '%Y-%m-%d')))
        code = str(row.get(mp['producto_codigo']) or '').strip()
        qty, price, cost = [decimal_number(row.get(mp[k])) for k in ('cantidad_vendida','precio_venta','costo_unitario')]
        discount_column = mp.get('descuento') or next((k for k in row if k.strip().casefold() in {'descuento','discount'}), None)
        discount = decimal_number(row.get(discount_column)) if discount_column else None
        discount_missing += discount is None
        discount_nonzero += discount is not None and discount != 0
        cost_missing += cost is None
        if day is None or not code or qty is None or price is None or qty < 0 or price < 0 or (cost is not None and cost < 0):
            invalid += 1
            continue
        days.add(day); codes.add(code); pairs.append((day,code))
        m = months.setdefault(day.strftime('%Y-%m'), {'units': Decimal(0), 'quantity_times_price': Decimal(0),
                                                     'known_quantity_times_cost': Decimal(0), 'rows': 0})
        m['units'] += qty; m['quantity_times_price'] += qty * price
        if cost is not None: m['known_quantity_times_cost'] += qty * cost
        m['rows'] += 1
    expected_days = {date(2026,7,1)+timedelta(days=i) for i in range(92)}
    result.update(days=len(days), first_day=str(min(days)) if days else None, last_day=str(max(days)) if days else None,
                  unique_products=len(codes), invalid_rows=invalid, duplicate_day_product=len(pairs)-len(set(pairs)),
                  missing_days=[str(d) for d in sorted(expected_days-days)], unexpected_days=[str(d) for d in sorted(days-expected_days)],
                  discount_nonzero_rows=discount_nonzero, discount_missing_rows=discount_missing, cost_missing_rows=cost_missing,
                  exact_92_by_9=(days == expected_days and len(codes)==9 and len(pairs)==828 and len(set(pairs))==828),
                  monthly_arithmetic={k:{n:str(v) if isinstance(v,Decimal) else v for n,v in m.items()} for k,m in months.items()})
    return result

def verify(select_source):
    require(sys.platform == 'win32', 'Ejecutar este verificador en Windows.')
    root = Path(os.environ.get('ProgramData',r'C:\ProgramData')) / 'AIVA' / 'Collector'
    cli = Path(os.environ.get('ProgramFiles',r'C:\Program Files')) / 'AIVA Collector' / 'aiva-collector-cli.exe'
    require(cli.is_file() and sha(cli)==CLI_SHA, 'La instalacion no coincide con el CLI RC7 verificado.')
    require('0.2.7rc7' in run([str(cli),'--version']), 'La version instalada no es RC7.')
    # Uses the installed binary's selection; explicitly prohibits migration.
    selected = json.loads(run([str(cli),'diagnose-config','--no-migrate']))
    require(selected.get('resolved') is True, 'No se encontro configuracion efectiva.')
    runtime = resolve_runtime_config(selected['selected_path'], migrate=False)
    config = runtime.config
    require((config.commerce_id,config.collector_id)==(COMMERCE,COLLECTOR), 'La identidad no es la del piloto autorizado.')
    candidates = list(root.rglob('Ventas_demo_RC7.xlsx'))
    expected = config.path('input_dir') / 'Ventas_demo_RC7.xlsx'
    if expected.is_file() and expected not in candidates: candidates.append(expected)
    source = candidates[0] if len(candidates)==1 else Path(select_source())
    require(source.is_file() and source.suffix.lower()=='.xlsx' and not source.is_symlink(), 'Seleccionar el Excel del piloto.')
    require(sha(source)==EXPECTED_SHA, 'El SHA del Excel no coincide con el archivo de tres meses. No se ingirio nada.')
    db = config.path('state_dir') / 'aiva_collector.db'
    for key in ('state_dir','queue_dir','output_dir','processed_dir','error_dir','mappings_dir','log_file'):
        if config.raw.get(key):
            require(config.path(key).resolve().is_relative_to(root.resolve()), 'Hay datos mutables fuera del respaldo previsto.')
    require(runtime.selected_path.resolve().is_relative_to(root.resolve()), 'Configuracion fuera del respaldo previsto.')
    xml = task_xml()
    run(['schtasks.exe','/Change','/TN',TASK,'/DISABLE'])
    require(task_disabled(), 'No se pudo dejar la tarea deshabilitada.')
    require(no_processes(), 'Cerra AIVA Collector y volve a abrir el verificador. La tarea quedo deshabilitada.')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
    parent = root.parent / ('Collector-backup-verificador-'+stamp)
    parent.mkdir()
    run(['icacls.exe',str(parent),'/inheritance:r','/grant:r','*S-1-5-18:(OI)(CI)F','*S-1-5-32-544:(OI)(CI)F'])
    evidence = backup(root,db,parent/'Collector',xml)
    require(no_processes() and task_disabled(), 'Collector cambio durante el respaldo; revisar.')
    state = local_state(db,config,source)
    source_check = analyze(source,config)
    require(sha(source)==EXPECTED_SHA, 'El Excel cambio durante la verificacion.')
    keys = ('source_schema_version','daily_source_id','business_timezone','price_semantics','daily_snapshot_complete','daily_complete_file_sha256')
    return {'verifier':'20261007','installed_version':VERSION,'sha256':EXPECTED_SHA,
            'commerce_id':COMMERCE,'collector_id':COLLECTOR,
            'configuration':{k:config.raw.get(k) for k in keys},
            'file_in_configured_input':source.parent.resolve()==config.path('input_dir').resolve(),
            'backup':evidence,'local_state':state,'excel':source_check,'task_disabled':True,
            'ingested':False,'messages_sent':0,'network_used':False}

def main():
    if '--self-check' in sys.argv:
        print(json.dumps({'verifier':'20261007','version':VERSION,'network_used':False}))
        return 0
    import tkinter as tk
    from tkinter import filedialog, messagebox
    ui = tk.Tk(); ui.withdraw()
    try:
        if not ctypes.windll.shell32.IsUserAnAdmin():
            raise Stop('Abrir el verificador con Ejecutar como administrador.')
        result = verify(lambda: filedialog.askopenfilename(title='Seleccionar Ventas_demo_RC7.xlsx',filetypes=[('Excel','*.xlsx')]))
    except Stop as error:
        result = {'verifier':'20261007','completed':False,'error':str(error),'ingested':False,'messages_sent':0}
    except Exception as error:
        result = {'verifier':'20261007','completed':False,'error_type':type(error).__name__,'ingested':False,'messages_sent':0}
    else:
        result['completed'] = True
    output = filedialog.asksaveasfilename(title='Guardar diagnostico para adjuntar en el chat',initialfile='AIVA-RC7-diagnostico.json',defaultextension='.json',filetypes=[('Diagnostico JSON','*.json')])
    if output:
        Path(output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        messagebox.showinfo('AIVA RC7', 'Diagnostico guardado. Adjunta ese JSON en el chat de Codex.\nNo se ingirieron datos ni se envio WhatsApp.' + ('\n'+result.get('error','Se encontro un bloqueo; ver JSON.') if not result['completed'] else ''))
    else:
        messagebox.showinfo('AIVA RC7','No se guardo el diagnostico. No se enviaron datos. Si la verificacion deshabilito la tarea, permanece deshabilitada.')
    ui.destroy()
    return 0 if result['completed'] else 2

if __name__ == '__main__':
    raise SystemExit(main())
