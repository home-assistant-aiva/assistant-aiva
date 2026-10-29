"""Synthetic RC9-style file and Assistant state; no installed state is read."""
import json
from datetime import date

import pytest

from aiva_collector.config import load_config
from aiva_collector.connection_config import load_connection
from aiva_collector.connection_setup import activate, preview, source_identity
from aiva_collector.connection_sync import _init
from aiva_collector.connectors.base import AccessError, Window
from aiva_collector.legacy_migration import legacy_review_plan, rollback_unstarted_upgrade
from aiva_collector.local_state import connect, local_db_path
from aiva_collector.source_setup import context_key


def _legacy_copy(tmp_path):
    folder = tmp_path / 'exports'
    folder.mkdir()
    (folder / 'ventas.csv').write_text('Fecha,Producto,Cantidad,Precio\n')
    config_path = tmp_path / 'config.json'
    raw = {'backend_url': 'https://backend.invalid', 'commerce_id': 'fictional-shop',
           'collector_id': 'synthetic-collector', 'state_dir': str(tmp_path / 'state'),
           'input_dir': str(folder), 'daily_source_id': 'source_existing_rc9',
           'column_mapping': {'fecha': 'Fecha', 'producto_nombre': 'Producto',
                              'cantidad_vendida': 'Cantidad', 'precio_venta': 'Precio'},
           'price_semantics': 'final_net', 'discount_semantics': 'per_line',
           'business_timezone': 'America/Argentina/Buenos_Aires',
           'decimal_conventions': {'precio_venta': 'dot'}, 'daily_snapshot_complete': True,
           'xlsx_sheet': '', 'xlsx_header_row': None}
    from aiva_collector.config import CollectorConfig
    raw['source_profile'] = {'context': context_key(CollectorConfig(raw, config_path)),
                             'headers': ['Cantidad', 'Fecha', 'Precio', 'Producto'], 'suffix': '.csv'}
    config_path.write_text(json.dumps(raw))
    config = load_config(config_path)
    with connect(local_db_path(config)) as conn:
        conn.execute("INSERT INTO upload_queue(queue_id,file_id,idempotency_key,payload_hash,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                     ('pending-existing', 'file-existing', 'key-existing', 'hash-existing', 'pending', '2026-10-01', '2026-10-01'))
    return config


def _activate_reviewed(config):
    plan = legacy_review_plan(config)
    assert plan['source_id'] == 'source_existing_rc9'
    assert plan['profile']['reader']['decimal_conventions'] == {'precio_venta': 'dot'}
    assert plan['profile']['complete_days'] is True
    assert any('cobertura' in item for item in plan['requires_review'])
    sample = [{'Fecha': '2026-10-01', 'Producto': 'Artículo', 'Cantidad': '2', 'Precio': '10.00'}]
    reviewed = preview(config, plan['profile'], plan['mapping'], Window(date(2026, 10, 1), date(2026, 10, 1)), sample=sample)
    assert source_identity(config, reviewed['profile']) == plan['source_id']
    return activate(config, reviewed)


def test_rc9_copy_preserves_identity_config_and_pending_queue_during_stage_and_rollback(tmp_path):
    config = _legacy_copy(tmp_path)
    original = config.config_path.read_bytes()
    activated = _activate_reviewed(config)
    assert activated['source_id'] == 'source_existing_rc9'
    assert config.config_path.read_bytes() == original
    with connect(local_db_path(config)) as conn:
        assert conn.execute("SELECT queue_id,status FROM upload_queue").fetchone()[:] == ('pending-existing', 'pending')
    archive = rollback_unstarted_upgrade(config)
    assert archive and archive.exists() and load_connection(config) is None
    assert config.config_path.read_bytes() == original
    with connect(local_db_path(config)) as conn:
        assert conn.execute("SELECT queue_id,status FROM upload_queue").fetchone()[:] == ('pending-existing', 'pending')


def test_assistant_state_copy_reconfiguration_keeps_source_and_refuses_change(tmp_path):
    config = _legacy_copy(tmp_path)
    first = _activate_reviewed(config)
    profile = dict(first['profile'])
    profile['cost_basis'] = 'current'
    assert source_identity(config, profile) == first['source_id']
    profile['suffix'] = '.xlsx'
    with pytest.raises(AccessError) as exc:
        source_identity(config, profile)
    assert exc.value.code == 'source_transition_required'


def test_rollback_requires_review_after_assistant_submission(tmp_path):
    config = _legacy_copy(tmp_path)
    _activate_reviewed(config)
    with connect(local_db_path(config)) as conn:
        _init(conn)
        conn.execute("INSERT INTO connection_batches(context,source_id,capture_key,payload_json,idempotency_key,status) VALUES(?,?,?,?,?,?)",
                     ('synthetic', 'source_existing_rc9', '2026-10-01', '{}', 'synthetic-id', 'pending'))
    with pytest.raises(AccessError) as exc:
        rollback_unstarted_upgrade(config)
    assert exc.value.code == 'rollback_review_required'
    assert load_connection(config)['source_id'] == 'source_existing_rc9'


def test_insufficient_space_blocks_activation_without_changing_state(tmp_path, monkeypatch):
    config = _legacy_copy(tmp_path)
    original = config.config_path.read_bytes()
    import aiva_collector.legacy_migration as migration
    from types import SimpleNamespace
    monkeypatch.setattr(migration.shutil, 'disk_usage', lambda _path: SimpleNamespace(free=1))
    with pytest.raises(AccessError) as exc:
        _activate_reviewed(config)
    assert exc.value.code == 'insufficient_space'
    assert load_connection(config) is None and config.config_path.read_bytes() == original
    with connect(local_db_path(config)) as conn:
        assert conn.execute("SELECT status FROM upload_queue WHERE queue_id='pending-existing'").fetchone()[0] == 'pending'


def test_legacy_number_format_change_needs_review(tmp_path):
    config = _legacy_copy(tmp_path)
    plan = legacy_review_plan(config)
    sample = [{'Fecha': '2026-10-01', 'Producto': 'Artículo', 'Cantidad': '2', 'Precio': '10,50'},
              {'Fecha': '2026-10-01', 'Producto': 'Otro', 'Cantidad': '3', 'Precio': '11,25'}]
    with pytest.raises(AccessError) as exc:
        preview(config, plan['profile'], plan['mapping'], Window(date(2026, 10, 1), date(2026, 10, 1)), sample=sample)
    assert exc.value.code == 'numeric_format_changed'
