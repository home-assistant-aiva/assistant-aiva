import json
from datetime import date

import pytest

from aiva_collector.config import CollectorConfig
from aiva_collector.connection_config import context, digest, load_connection, reject_secrets, recommendations, validate_profile
from aiva_collector.connection_setup import activate, preview, load_draft, save_draft
from aiva_collector.connectors.base import AccessError, Window
from aiva_collector.source_credentials import CredentialVault


def config(tmp_path, commerce='a', backend='https://backend.invalid/API'):
    return CollectorConfig({'state_dir':str(tmp_path), 'backend_url':backend,'commerce_id':commerce,'collector_id':'collector'}, tmp_path/'config.json')


def test_credentials_have_no_plaintext_fallback_or_cross_tenant_path(tmp_path):
    cfg=config(tmp_path)
    vault=CredentialVault(cfg,'source')
    if __import__('sys').platform != 'win32':
        with pytest.raises(AccessError):vault.store({'password':'synthetic-only'})
        assert not vault.path.exists()
    else:
        vault.store({'password':'synthetic-only'})
        assert 'synthetic-only' not in vault.path.read_text()
        assert vault.load()['password']=='synthetic-only'
        vault.delete()
        assert not vault.load()
    assert vault.path != CredentialVault(config(tmp_path,'b'),'source').path
    assert context(cfg) != context(config(tmp_path,backend='https://backend.invalid/api'))
    for p in ({'password':'synthetic'}, {'reader':{'token':'synthetic'}}, {'oauth':{'client_secret':'synthetic'}}):
        with pytest.raises(AccessError):reject_secrets(p)
    save_draft(cfg, {'kind':'rest','state':'profile_required'})
    assert load_draft(config(tmp_path,'b')) == {}


def test_profile_cannot_override_binding_or_execute_sql(tmp_path):
    with pytest.raises(AccessError):
        validate_profile({'kind':'files','folder':str(tmp_path),'reader':{'commerce_id':'other'}})
    with pytest.raises(AccessError):
        validate_profile({'kind':'sqlite','path':'x','table':'y','columns':['date'],'date_column':'date','location_column':'branch'})


def test_recommendation_uses_evidence_not_connection_type():
    options=recommendations([{'kind':'rest','evidence':{}},{'kind':'files','evidence':{'access_tested':True,'sales':True,'costs':True,'automated':True,'read_only':True}}])
    assert options[0]['kind']=='files' and options[1]['recommendation']=='needs_verification'


def test_old_confirmation_cannot_change_source_or_mapping(tmp_path):
    cfg=config(tmp_path)
    profile={'kind':'files','folder':str(tmp_path),'timezone':'America/Argentina/Buenos_Aires','reader':{'price_semantics':'final_net','discount_semantics':'per_line'}}
    mapping={k:k for k in ('fecha','producto_nombre','cantidad_vendida','precio_venta')}
    sample=[dict(zip(mapping, ['2026-10-01','Producto',2,100]))]
    w=Window(date(2026,10,1),date(2026,10,1))
    reviewed=preview(cfg,profile,mapping,w,sample=sample)
    altered=dict(reviewed, mapping={**mapping,'precio_venta':'cantidad_vendida'})
    with pytest.raises(AccessError):activate(cfg,altered)
    activate(cfg,reviewed)
    with pytest.raises(AccessError):activate(cfg,reviewed)
    with pytest.raises(AccessError):activate(config(tmp_path,'b'),reviewed)
    assert load_connection(cfg)['mapping']==mapping


def test_wizard_file_profile_uses_selected_path_without_worker_tk_access(tmp_path):
    from types import SimpleNamespace
    from aiva_collector.connection_wizard import ConnectionWizard
    class Value:
        def __init__(self, value):self.value=value
        def get(self):return self.value
    path=tmp_path/'source.csv';path.write_text('Fecha,Producto,Cantidad,Precio\n2026-10-01,Producto,1,10\n')
    view=SimpleNamespace(profile={'kind':'files'}, vars={'source_path':Value(str(path)), 'sheet':Value(''), 'header':Value('')})
    result=ConnectionWizard.get_profile(view)
    assert result['folder']==str(tmp_path)
    assert result['suffix']=='.csv'


def test_sqlite_internal_database_copy_is_never_a_commerce_source(tmp_path):
    import sqlite3
    from aiva_collector.connectors.sqlite import SQLiteConnector
    path=tmp_path/'renamed-copy.sqlite'
    with sqlite3.connect(path) as conn:conn.execute('CREATE TABLE processed_files(day TEXT)')
    reader=SQLiteConnector({'path':str(path),'table':'processed_files','columns':['day'],'date_column':'day'})
    with pytest.raises(AccessError) as caught:reader.read(Window(date(2026,10,1),date(2026,10,1)))
    assert caught.value.code=='internal_database_forbidden'


def test_oauth_refresh_preserves_rotating_token_and_expiration(monkeypatch):
    from aiva_collector import oauth_access
    saved=[]
    calls=[]
    monkeypatch.setattr(oauth_access, '_token', lambda profile, data: (calls.append(data) or {'access_token':'new-synthetic', 'refresh_token':'rotated-synthetic', 'expires_at':9999999999}))
    profile={'oauth':{'client_id':'public-id'}}
    renewed=oauth_access.refresh_if_needed(profile,{'refresh_token':'old-synthetic','expires_at':0},saved.append)
    assert renewed==saved[0] and calls[0]['grant_type']=='refresh_token'
    assert 'client_secret' not in calls[0]
    with pytest.raises(AccessError):oauth_access.refresh_if_needed(profile,{'expires_at':0},saved.append)


def test_diagnostic_contains_only_active_binding_counts(tmp_path):
    import sqlite3, zipfile
    from aiva_collector.connection_diagnostics import write_diagnostics
    from aiva_collector.local_state import connect, local_db_path
    cfg=config(tmp_path)
    conn=connect(local_db_path(cfg))
    conn.execute("CREATE TABLE connection_batches(context TEXT,source_id TEXT,status TEXT,payload_json TEXT)")
    conn.execute("INSERT INTO connection_batches VALUES(?,?,?,?)",(context(config(tmp_path,'b')),'other-source','pending','PRIVATE-OTHER-COMMERCE'))
    conn.commit();conn.close()
    archive=write_diagnostics(cfg,tmp_path/'diagnostic','test.zip')
    with zipfile.ZipFile(archive) as z:
        result=z.read('diagnostic.json').decode()
        assert 'PRIVATE-OTHER-COMMERCE' not in result and 'other-source' not in result
        assert 'password' not in result and str(tmp_path) not in result
        assert set(z.namelist())=={'diagnostic.json'}


def test_corrupt_legacy_queue_of_another_commerce_is_untouched(tmp_path):
    from types import SimpleNamespace
    from aiva_collector.local_state import connect,local_db_path,upsert_detected_file,update_file_state
    from aiva_collector.offline_queue import enqueue_payload,process_queue
    cfg=config(tmp_path,'a')
    other=config(tmp_path,'b')
    source=tmp_path/'source.csv';source.write_text('synthetic')
    conn=connect(local_db_path(cfg))
    upsert_detected_file(conn,file_id='other-file',commerce_id='b',collector_id='collector',backend_url=other.backend_url,path=source,file_sha256='0'*64)
    update_file_state(conn,'other-file',status='pending_send')
    enqueue_payload(conn,other,file_id='other-file',payload={'commerce_id':'b','collector_id':'collector','fecha_inicio':'2026-10-01','fecha_fin':'2026-10-01','productos_resumidos':[]})
    item=conn.execute('SELECT * FROM upload_queue').fetchone()
    __import__('pathlib').Path(item['payload_json_path']).write_text('{invalid')
    result=process_queue(conn,cfg,client=SimpleNamespace(send_summary=lambda value:pytest.fail('cross-tenant send')))
    assert result.skipped==1
    assert conn.execute('SELECT status FROM upload_queue').fetchone()[0]=='pending'
    assert conn.execute('SELECT status FROM processed_files').fetchone()[0]=='pending_send'
    conn.close()
