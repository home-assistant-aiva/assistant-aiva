from datetime import date, timedelta
from decimal import Decimal
import json
from pathlib import Path
import sqlite3

import pytest
from openpyxl import Workbook
from aiva_collector.config import CollectorConfig
from aiva_collector import pilot_verifier as v


def workbook(tmp_path, discount=0, omit=False):
    p=tmp_path/'demo.xlsx'; w=Workbook(); s=w.active
    s.append(['Fecha','Código producto','Producto','Cantidad','Precio venta','Costo','Descuento'])
    for i in range(92):
        for code in range(9):
            if omit and i==91 and code==8: continue
            s.append([date(2026,7,1)+timedelta(days=i),str(code+1),'Synthetic',2,10,4,discount])
    w.save(p)
    c=CollectorConfig({'source_schema_version':'2.0.0','column_mapping':{'fecha':'Fecha','producto_codigo':'Código producto','producto_nombre':'Producto','cantidad_vendida':'Cantidad','precio_venta':'Precio venta','costo_unitario':'Costo'}},tmp_path/'config.json')
    return p,c


def test_independent_arithmetic_preserves_uncertainty(tmp_path):
    p,c=workbook(tmp_path,discount=1)
    before=v.sha(p); r=v.analyze(p,c)
    assert v.sha(p)==before and r['exact_92_by_9']
    assert r['discount_nonzero_rows']==828
    assert r['monthly_arithmetic']['2026-09']=={'units':'540','quantity_times_price':'5400','known_quantity_times_cost':'2160','rows':270}
    assert not r['price_semantics_verified'] and not r['completeness_certified']
    assert not r['synthetic_provenance_verified']
    assert 'gross_profit' not in json.dumps(r)


def test_missing_pair_not_complete(tmp_path):
    p,c=workbook(tmp_path,omit=True)
    r=v.analyze(p,c)
    assert r['days']==92 and not r['exact_92_by_9']


def test_backup_restores_sqlite_and_preserves_original(tmp_path):
    root=tmp_path/'data';root.mkdir();db=root/'local.db'
    with sqlite3.connect(db) as conn:
        conn.execute('create table preserved(value text)');conn.execute("insert into preserved values ('private')")
    (root/'private-token').write_text('secret-stays-local')
    old=v.sha(db);parent=tmp_path/'protected';parent.mkdir()
    r=v.backup(root,db,parent/'Collector','<Task/>')
    assert r['sqlite_integrity']==r['restore_integrity']=='ok'
    assert v.sha(db)==old
    assert (parent/'restore-verified/private-token').read_text()=='secret-stays-local'
    assert 'secret-stays-local' not in json.dumps(r)


def test_state_is_read_only_scoped_and_sanitized(tmp_path):
    db=tmp_path/'local.db';source=tmp_path/'renamed.xlsx'
    with sqlite3.connect(db) as c:
        c.execute('create table processed_files(status,source_schema_version,backend_summary_id,file_path,file_sha256,commerce_id,collector_id,backend_url)')
        c.execute('create table upload_queue(status)')
        for commerce in [v.COMMERCE,'other']:
            c.execute('insert into processed_files values (?,?,?,?,?,?,?,?)',('sent','1.0.0','summary','private/old.xlsx',v.EXPECTED_SHA,commerce,v.COLLECTOR,'https://backend.invalid'))
    before=v.sha(db)
    cfg=CollectorConfig({'commerce_id':v.COMMERCE,'collector_id':v.COLLECTOR,'backend_url':'https://backend.invalid'},tmp_path/'config.json')
    r=v.local_state(db,cfg,source)
    assert r['matching_sha_records']==[{'status':'sent','schema':'1.0.0','summary_id':'summary','same_path':False}]
    assert 'private' not in json.dumps(r) and v.sha(db)==before


def test_rejects_backup_symlink(tmp_path):
    root=tmp_path/'data';root.mkdir();db=root/'local.db'
    with sqlite3.connect(db): pass
    try: (root/'link').symlink_to(db)
    except OSError: pytest.skip('Symlink privilege unavailable')
    with pytest.raises(v.Stop):v.backup(root,db,tmp_path/'backup','<Task/>')
