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
