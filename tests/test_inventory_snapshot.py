import csv
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from aiva_collector.config import CollectorConfig
from aiva_collector.connection_config import digest, save_connection
from aiva_collector.connection_sync import synchronize
from aiva_collector.connectors.base import Window
from aiva_collector.inventory import build_inventory
from aiva_collector.local_state import connect, local_db_path
from aiva_collector.errors import BackendError
from aiva_collector.connection_sync import state_path
import json


MAPPING = {"fecha":"Fecha","producto_codigo":"Código","producto_nombre":"Producto",
    "cantidad_vendida":"Cantidad","precio_venta":"Precio Unit.","costo_unitario":"Costo Unit.",
    "stock_actual":"Existencia","fecha_stock":"Fecha Existencia",
    "precio_actual":"Precio Venta Actual","fecha_valores_actuales":"Fecha Costo y Precio",
    "periodo_desde":"Período Desde","periodo_hasta":"Período Hasta"}


def write_file(path, *, stock="0", date_text="17/10/2026", second=None,
               sale_date="17/10/2026", period_start="01/10/2026", period_end="17/10/2026"):
    with path.open("w",encoding="utf-8-sig",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=list(MAPPING.values()),delimiter=";")
        writer.writeheader()
        writer.writerow(dict(zip(MAPPING.values(),(sale_date,"A","Producto A","2","1.234,50",
            "789,10",stock,date_text,"1.500,00",date_text,period_start,period_end))))
        if second is not None:
            writer.writerow(dict(zip(MAPPING.values(),(sale_date,"A","Producto A","1","1.234,50",
                "789,10",second,date_text,"1.500,00",date_text,period_start,period_end))))


def fixture(tmp_path, monkeypatch):
    monkeypatch.setenv("AIVA_INVENTORY_TEST_TOKEN","synthetic-token")
    folder=tmp_path/"exports";folder.mkdir()
    path=folder/"ventas.csv";write_file(path)
    config=CollectorConfig({"backend_url":"https://backend.invalid","commerce_id":"fictional",
        "collector_id":"collector_fictional","collector_token_env":"AIVA_INVENTORY_TEST_TOKEN",
        "state_dir":str(tmp_path/"state"),"input_dir":str(folder)},tmp_path/"config.json")
    profile={"kind":"files","folder":str(folder),"suffix":".csv","timezone":"America/Argentina/Buenos_Aires",
        "complete_days":True,"cost_basis":"current","reader":{"price_semantics":"final_net"}}
    setup=save_connection(config,profile,MAPPING,Window(date(2026,10,17),date(2026,10,17)),confirmed=True)
    return config,setup,path


def test_inventory_distinguishes_zero_undated_and_conflict(tmp_path,monkeypatch):
    config,setup,path=fixture(tmp_path,monkeypatch)
    captured=build_inventory(config,setup,path)
    by_kind={item["kind"]:item for item in captured["observations"]}
    assert by_kind["stock"]["value"]=="0" and by_kind["stock"]["observed_on"]=="2026-10-17"
    assert by_kind["current_cost"]["value"]=="789.10"
    assert by_kind["current_price"]["value"]=="1500.00"
    write_file(path,stock="2",second="3")
    conflict=build_inventory(config,setup,path)
    assert next(item for item in conflict["observations"] if item["kind"]=="stock")["quality"]=="conflict"
    write_file(path,date_text="")
    undated=build_inventory(config,setup,path)
    assert all(item["quality"]=="undated" for item in undated["observations"])


class Client:
    def __init__(self,features=None):
        self.features=features or ["daily_v2","dated_stock","cost_basis","empty_daily","inventory_snapshot_v1"]
        self.inventory=[];self.sales=[]
    def service_status(self):
        return {"ingestion_features":self.features,"decision_readiness":{"capabilities":[]}}
    def send_inventory(self,payload):
        self.inventory.append(payload)
        return {"duplicate":False}
    def send_summary(self,payload):
        self.sales.append(payload)
        return {"ok":True}


def test_inventory_sent_once_and_backend_feature_required(tmp_path,monkeypatch):
    config,setup,path=fixture(tmp_path,monkeypatch)
    now=datetime(2026,10,18,12,tzinfo=timezone.utc)
    old=Client(["daily_v2","dated_stock","cost_basis","empty_daily"])
    rejected=synchronize(config,force=True,client=old,now=now)
    assert rejected["code"]=="backend_upgrade_required" and not old.sales
    assert not old.inventory
    client=Client()
    first=synchronize(config,force=True,client=client,now=now)
    assert first["state"]=="sync_completed" and len(client.inventory)==1
    second=synchronize(config,force=True,client=client,now=now)
    assert second["state"]=="sync_completed" and len(client.inventory)==1
    write_file(path,stock="4")
    third=synchronize(config,force=True,client=client,now=now)
    assert third["state"]=="sync_completed" and len(client.inventory)==2
    conn=connect(local_db_path(config))
    assert conn.execute("SELECT COUNT(*) FROM connection_inventory_batches").fetchone()[0]==2
    assert conn.execute("SELECT COUNT(*) FROM connection_inventory_batches WHERE payload_json IS NULL").fetchone()[0]==2
    conn.close()


def test_new_options_keep_existing_source_identity(tmp_path,monkeypatch):
    config,setup,path=fixture(tmp_path,monkeypatch)
    profile={**setup["profile"],"history_mode":"three_closed_months_current","include_today":False,
             "inventory_confirmation":{"observed_on":"2026-10-17","source_id":setup["source_id"],
                                       "file_sha256":"synthetic"}}
    updated=save_connection(config,profile,MAPPING,Window(date(2026,10,17),date(2026,10,17)),
                            confirmed=True,expected=digest(setup))
    assert updated["source_id"]==setup["source_id"]
    assert updated["configuration_revision"]==setup["configuration_revision"]+1


def test_simultaneous_overlap_stops_before_any_upload(tmp_path,monkeypatch):
    config,setup,path=fixture(tmp_path,monkeypatch)
    second=path.parent/"otra.csv"
    write_file(second,stock="2")
    client=Client()
    result=synchronize(config,force=True,client=client,now=datetime(2026,10,18,12,tzinfo=timezone.utc))
    assert result["code"]=="overlapping_files"
    assert not client.inventory and not client.sales


def test_twelve_closed_days_resume_without_reprocessing_confirmed_history(tmp_path,monkeypatch):
    config,setup,path=fixture(tmp_path,monkeypatch)
    setup=save_connection(config,setup['profile'],MAPPING,Window(date(2026,10,1),date(2026,10,17)),
                          confirmed=True,expected=digest(setup))
    write_file(path,sale_date="05/10/2026",period_end="05/10/2026")
    client=Client()
    first=synchronize(config,force=True,client=client,now=datetime(2026,10,6,12,tzinfo=timezone.utc))
    assert first['state']=='sync_completed' and first['last_confirmed_business_date']=='2026-10-05'
    assert len(client.sales)==5
    write_file(path,sale_date="17/10/2026")
    second=synchronize(config,force=True,client=client,now=datetime(2026,10,18,12,tzinfo=timezone.utc))
    assert second['state']=='sync_completed' and second['last_confirmed_business_date']=='2026-10-17'
    assert len(client.sales)==17 and second['sent']==12
    assert second['missing_days']==0
    conn=connect(local_db_path(config))
    assert conn.execute('SELECT COUNT(*) FROM connection_day_confirmations').fetchone()[0]==17
    conn.close()


def test_pending_inventory_recovers_without_duplicate_or_loss(tmp_path,monkeypatch):
    config,setup,path=fixture(tmp_path,monkeypatch)
    class Flaky(Client):
        fail=True
        def send_inventory(self,payload):
            if self.fail:
                self.fail=False
                raise BackendError('synthetic temporary failure',status_code=503)
            return super().send_inventory(payload)
    client=Flaky()
    now=datetime(2026,10,18,12,tzinfo=timezone.utc)
    first=synchronize(config,force=True,client=client,now=now)
    assert first['state']=='ready' and first['code']=='backend_temporary'
    conn=connect(local_db_path(config))
    assert conn.execute("SELECT status FROM connection_inventory_batches").fetchone()[0]=='pending'
    conn.close()
    second=synchronize(config,force=True,client=client,now=now)
    assert second['state']=='sync_completed' and len(client.inventory)==1
    conn=connect(local_db_path(config))
    assert conn.execute("SELECT status FROM connection_inventory_batches").fetchone()[0]=='sent'
    conn.close()


def test_other_windows_user_records_local_credential_failure(tmp_path,monkeypatch):
    config,setup,path=fixture(tmp_path,monkeypatch)
    monkeypatch.delenv('AIVA_INVENTORY_TEST_TOKEN')
    client=Client()
    result=synchronize(config,force=True,client=client,now=datetime(2026,10,18,12,tzinfo=timezone.utc))
    assert result['code']=='credential_unavailable' and result['state']=='intervention_required'
    assert json.loads(state_path(config).read_text())['code']=='credential_unavailable'
    assert not client.inventory and not client.sales
