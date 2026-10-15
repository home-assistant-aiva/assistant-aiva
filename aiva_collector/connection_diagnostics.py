"""Allowlisted, binding-scoped diagnostics; never export profiles, logs or payloads."""
import json
import sqlite3
import zipfile
from pathlib import Path

from .connection_config import context, load_connection
from .connection_sync import state_path
from .local_state import local_db_path


def safe_diagnostics(config):
    setup = load_connection(config)
    status = json.loads(state_path(config).read_text()) if state_path(config).exists() else {}
    allowed = ('state','configuration_revision','rows','sent','duplicates','missing_days','code','last_success','next_attempt','retry_count')
    data = {'version':config.collector_version, 'context':context(config), 'source_id':setup['source_id'] if setup else None,
            'kind':setup['profile']['kind'] if setup else 'legacy_files', 'status':{k:status.get(k) for k in allowed},
            'https':config.backend_url.startswith('https://'), 'pending':{}, 'legacy_pending':0}
    path=local_db_path(config)
    if path.exists():
        with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=3) as conn:
            data['local_state'] = {'quick_check': conn.execute('PRAGMA quick_check').fetchone()[0]}
            tables={r[0] for r in conn.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
            data['local_state']['table_names'] = sorted(tables)
            columns = {r[1] for r in conn.execute('PRAGMA table_info(processed_files)')} if 'processed_files' in tables else set()
            data['local_state']['legacy_unscoped_excluded'] = bool(columns and not {'commerce_id','collector_id','backend_url'} <= columns)
            if setup and 'connection_batches' in tables:
                data['pending']={r[0]:r[1] for r in conn.execute('SELECT status,count(*) FROM connection_batches WHERE context=? AND source_id=? GROUP BY status',(context(config),setup['source_id']))}
            if {'processed_files','upload_queue'} <= tables and {'commerce_id','collector_id','backend_url'} <= columns:
                data['legacy_pending']=conn.execute("""SELECT count(*) FROM upload_queue q JOIN processed_files f ON f.file_id=q.file_id
                    WHERE f.commerce_id=? AND f.collector_id=? AND lower(rtrim(f.backend_url,'/'))=lower(rtrim(?,'/'))
                    AND q.status IN ('pending','retrying','processing')""",(config.commerce_id,config.collector_id,config.backend_url)).fetchone()[0]
    return data


def write_diagnostics(config, directory, filename):
    directory.mkdir(parents=True,exist_ok=True)
    path=directory/filename
    with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('diagnostic.json',json.dumps(safe_diagnostics(config),ensure_ascii=True,indent=2))
    return path
