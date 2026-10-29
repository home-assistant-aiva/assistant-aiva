import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from aiva_collector.config import CollectorConfig
from aiva_collector.connection_config import context, digest, load_connection, period, save_connection, set_paused
from aiva_collector.connection_setup import activate, preview
from aiva_collector.connection_sync import build_capture, connection_lock, state_path, synchronize
from aiva_collector.connectors.base import AccessError, Reading, Window
from aiva_collector.errors import BackendError
from aiva_collector.local_state import connect, local_db_path

MAPPING = {k:k for k in ('fecha', 'producto_nombre', 'producto_codigo', 'cantidad_vendida', 'precio_venta', 'costo_unitario', 'stock_actual', 'fecha_stock')}
NOW = datetime(2026,10,3,12,tzinfo=timezone.utc)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv('SYNTHETIC_COLLECTOR', 'not-a-real-secret')
    config = CollectorConfig({'backend_url': 'https://backend.invalid', 'commerce_id': 'synthetic', 'collector_id': 'reader',
        'state_dir': str(tmp_path/'state'), 'input_dir': str(tmp_path/'exports'), 'collector_token_env': 'SYNTHETIC_COLLECTOR'}, tmp_path/'config.json')
    profile = {'kind': 'sqlite', 'path': str(tmp_path/'source.db'), 'table': 'sales', 'columns': list(MAPPING), 'date_column': 'fecha',
        'timezone': 'America/Argentina/Buenos_Aires', 'complete_days': True, 'cost_basis': 'historical',
        'reader': {'price_semantics': 'final_net', 'discount_semantics': 'per_line'}}
    window = Window(date(2026,10,1), date(2026,10,2))
    value = save_connection(config, profile, MAPPING, window, confirmed=True, review_days=1)
    return config, profile, value


def row(day='2026-10-01', stock=0, price=100):
    return dict(zip(MAPPING, [day, 'Producto', '001', 2, price, 40, stock, day]))


class Reader:
    def __init__(self):
        self.price = 100
        self.calls = []
    def read(self, window, **kw):
        self.calls.append(window)
        return Reading([row(str(window.start), price=self.price)], complete=True)
    def close(self): pass


class Client:
    def __init__(self):
        self.payloads = []
        self.fail = False
        self.received = set()
    def service_status(self):
        return {'ingestion_features': ['daily_v2', 'dated_stock', 'cost_basis', 'empty_daily'], 'decision_readiness': {'capabilities': []}}
    def send_summary(self, payload):
        from aiva_collector.summarizer import idempotency_key
        self.payloads.append(payload)
        key = idempotency_key(payload)
        if self.fail:
            self.received.add(key)  # server received; response was lost
            raise BackendError('synthetic network loss')
        if key in self.received:
            raise BackendError('duplicate', status_code=409)
        self.received.add(key)
        return {'ok': True}


def test_period_closed_day_and_not_calendar_months():
    w = period(90, timezone='America/Argentina/Buenos_Aires', now=NOW)
    assert w.end == date(2026,10,2)
    assert (w.end-w.start).days == 89
    assert period(30, now=NOW, include_today=True).end == date(2026,10,3)
    assert period(now=datetime(2026,10,29,12,tzinfo=timezone.utc),mode='three_closed_months_current').start == date(2026,7,1)
    assert period(now=datetime(2026,10,29,12,tzinfo=timezone.utc),mode='three_closed_months_current').end == date(2026,10,28)
    assert period(now=datetime(2026,11,1,12,tzinfo=timezone.utc),mode='three_closed_months_current') == Window(date(2026,8,1),date(2026,10,31))
    assert period(now=datetime(2027,1,15,12,tzinfo=timezone.utc),mode='three_closed_months_current') == Window(date(2026,10,1),date(2027,1,14))


def test_snapshot_zero_dated_stock_current_partial_cost_and_negative(setup):
    cfg, _, value = setup
    w = Window(date(2026,10,1),date(2026,10,1))
    summary, _ = build_capture(cfg,value,Reading([row()],complete=True),w,1,features=['dated_stock','cost_basis'],today=date(2026,10,1))
    metric = summary['daily_snapshot']['metrics'][0]
    assert metric['closing_stock'] == '0.000000' and metric['stock_as_of_date'] == '2026-10-01'
    assert summary['daily_snapshot']['coverage'][0]['status'] == 'partial'
    value['profile']['cost_basis'] = 'current'
    summary, _ = build_capture(cfg,value,Reading([row()],complete=True),w,2,features=['dated_stock','cost_basis'])
    assert summary['daily_snapshot']['metrics'][0]['cogs'] is None
    assert summary['productos_resumidos'][0]['margen_bruto_estimado'] is None
    with pytest.raises(AccessError):
        build_capture(cfg,value,Reading([row(stock=-1)],complete=True),w,3)


def test_confirm_before_checkpoint_recovery_and_corrections(setup):
    cfg, _, value = setup
    client, reader = Client(), Reader()
    client.fail = True
    first = synchronize(cfg,force=True,client=client,connector=reader,now=NOW)
    assert first['code'] == 'backend_temporary' and first.get('last_success') is None
    conn = connect(local_db_path(cfg))
    assert conn.execute("SELECT status FROM connection_batches").fetchone()[0] == 'pending'
    conn.close()
    payload = client.payloads[0]
    client.fail = False
    result = synchronize(cfg,force=True,client=client,connector=reader,now=NOW)
    assert result['duplicates'] >= 1 and result['last_success']
    assert client.payloads[1] == payload  # retry preserves revision and payload
    count = len(client.received)
    synchronize(cfg,force=True,client=client,connector=reader,now=NOW)
    assert len(client.received) == count
    reader.price = 110
    synchronize(cfg,force=True,client=client,connector=reader,now=NOW)
    assert len(client.received) == count + 1  # recent day correction only
    assert client.payloads[-1]['daily_snapshot']['revision'] > payload['daily_snapshot']['revision']


def test_history_expansion_same_source_and_tenant_isolation(setup):
    cfg, profile, old = setup
    client, reader = Client(), Reader()
    synchronize(cfg,force=True,client=client,connector=reader,now=NOW)
    expanded = save_connection(cfg,profile,MAPPING,Window(date(2026,9,30),date(2026,10,2)),confirmed=True,expected=digest(old),review_days=1)
    assert expanded['source_id'] == old['source_id']
    synchronize(cfg,force=True,client=client,connector=reader,now=NOW)
    assert any(p['fecha_inicio']=='2026-09-30' for p in client.payloads)
    other = CollectorConfig({**cfg.raw,'commerce_id':'other'},cfg.config_path)
    assert load_connection(other) is None
    with pytest.raises(AccessError):
        save_connection(cfg,profile,MAPPING,Window(date(2026,9,1),date(2026,10,2)),confirmed=True,expected=digest(old))
    with connection_lock(cfg):
        with pytest.raises(AccessError):
            synchronize(cfg,force=True,client=client,connector=reader,now=NOW)
    set_paused(cfg,True)
    assert synchronize(cfg,force=True,client=client,connector=reader,now=NOW)['state']=='paused'


def test_read_failure_never_sends_partial_page_or_advances(setup):
    cfg, _, _ = setup
    class Broken(Reader):
        def read(self, *a, **kw):
            raise AccessError('provider_temporary','safe',retry_after=75)
    c = Client()
    result = synchronize(cfg,force=True,client=c,connector=Broken(),now=NOW)
    assert result['code']=='provider_temporary' and not c.payloads
    assert result['next_attempt']==NOW.timestamp()+75


def test_file_expansion_counts_and_selected_sheet(tmp_path):
    from openpyxl import Workbook
    from aiva_collector.connectors.files import FilesConnector
    path = tmp_path/'sales.xlsx'
    wb = Workbook()
    wb.active.title='Catalogo'
    wb.active.append(['Producto','Precio']);wb.active.append(['Otro',999])
    sheet=wb.create_sheet('Ventas');sheet.append(list(MAPPING))
    sheet.append(list(row('2026-09-30').values()));sheet.append(list(row('2026-10-01').values()));wb.save(path)
    p={'kind':'files','folder':str(tmp_path),'mapping':MAPPING,'reader':{'xlsx_sheet':'Ventas'}}
    reading=FilesConnector(p).read(Window(date(2026,10,1),date(2026,10,1)))
    assert len(reading.rows)==1 and reading.outside==1
    assert len(FilesConnector(p).read(Window(date(2026,9,30),date(2026,10,1))).rows)==2


def test_illegible_stock_requires_review_instead_of_looking_absent(setup):
    cfg, _, value=setup
    with pytest.raises(AccessError) as caught:
        build_capture(cfg,value,Reading([row(stock='inventario ilegible')],complete=True),Window(date(2026,10,1),date(2026,10,1)),1)
    assert caught.value.code=='invalid_stock'
