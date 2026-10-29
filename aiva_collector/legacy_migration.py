"""Review-only bridge from the RC9 file setup to the connection assistant.

The legacy config and queue remain authoritative until an operator previews and
activates the proposed profile through connection_setup.activate.
"""
import os
import shutil
import sqlite3
import uuid

from .connection_config import connection_path, load_connection
from .connection_sync import connection_lock
from .connectors.base import AccessError
from .local_state import local_db_path
from .source_setup import context_key


def migration_space_plan(config, *, export_bytes=0, build_bytes=0):
    """Conservative local budget for a DB backup, rollback copy, WAL and input."""
    state_dir = config.path('state_dir')
    anchor = state_dir
    while not anchor.exists():
        anchor = anchor.parent
    database = local_db_path(config)
    db_bytes = database.stat().st_size if database.exists() else 0
    wal = database.with_name(database.name + '-wal')
    wal_bytes = wal.stat().st_size if wal.exists() else 0
    queue_dir = config.optional_path('queue_dir')
    queue_bytes = sum(path.stat().st_size for path in queue_dir.glob('*.json') if path.is_file()) if queue_dir and queue_dir.exists() else 0
    required = 3 * db_bytes + 2 * wal_bytes + 2 * queue_bytes + 2 * export_bytes + build_bytes + 64 * 1024 * 1024
    free = shutil.disk_usage(anchor).free
    return {'free_bytes': free, 'required_bytes': required, 'db_bytes': db_bytes,
            'wal_bytes': wal_bytes, 'queue_bytes': queue_bytes, 'export_bytes': export_bytes,
            'build_bytes': build_bytes}


def require_migration_space(config, *, export_bytes=0, build_bytes=0):
    plan = migration_space_plan(config, export_bytes=export_bytes, build_bytes=build_bytes)
    if plan['free_bytes'] < plan['required_bytes']:
        raise AccessError('insufficient_space', 'Falta espacio para respaldo, migración y reversión. Conservá históricos y respaldos; liberá espacio de forma revisada antes de continuar.')
    return plan


def legacy_review_plan(config):
    raw = config.raw
    legacy = raw.get('source_profile') or {}
    source_id = raw.get('daily_source_id')
    if not source_id or legacy.get('context') != context_key(config):
        raise AccessError('legacy_review_required', 'La fuente anterior no tiene identidad y contexto acreditados. Revisá su configuración original.')
    suffix = legacy.get('suffix')
    if suffix not in {'.csv', '.xlsx'}:
        raise AccessError('legacy_review_required', 'No se puede migrar automáticamente el formato de archivo anterior.')
    mapping = config.column_mapping
    if not {'fecha', 'producto_nombre', 'cantidad_vendida', 'precio_venta'} <= mapping.keys():
        raise AccessError('legacy_review_required', 'Falta un campo obligatorio en el mapeo anterior.')
    reader = {'xlsx_sheet': raw.get('xlsx_sheet') or '',
              'xlsx_header_row': raw.get('xlsx_header_row'),
              'decimal_conventions': raw.get('decimal_conventions') or {},
              'price_semantics': raw.get('price_semantics'),
              'discount_semantics': raw.get('discount_semantics')}
    if reader['price_semantics'] not in {'final_net', 'gross_before_discount'} or reader['discount_semantics'] not in {'per_unit', 'per_line', 'percentage'}:
        raise AccessError('legacy_review_required', 'Revisá el significado anterior de precio y descuento.')
    profile = {'kind': 'files', 'folder': str(config.path('input_dir').resolve()), 'suffix': suffix,
               'timezone': raw.get('business_timezone') or 'America/Argentina/Buenos_Aires',
               'semantics': 'whole_day_snapshot', 'scope': 'whole_commerce',
               'complete_days': raw.get('daily_snapshot_complete') is True,
               'cost_basis': 'unknown', 'reader': reader, 'headers': legacy.get('headers') or []}
    reviews = ['Confirmar cobertura diaria y rango exportado; una venta completa no acredita inventario completo.',
               'Confirmar fecha y origen de cada valor de stock, costo y precio actual.']
    if 'costo_unitario' in mapping:
        reviews.append('Confirmar si el costo es histórico, actual o desconocido; la configuración anterior no lo acredita.')
    if not {'periodo_desde', 'periodo_hasta'} <= mapping.keys():
        reviews.append('Sin rango explícito de exportación, los días vacíos no quedan confirmados.')
    export_bytes = max((path.stat().st_size for path in config.path('input_dir').glob('*')
                        if path.is_file() and path.suffix.lower() == suffix), default=0)
    space = migration_space_plan(config, export_bytes=export_bytes)
    return {'source_id': source_id, 'profile': profile, 'mapping': mapping,
            'space': space,
            'requires_review': reviews, 'legacy_config_path': str(config.config_path)}


def rollback_unstarted_upgrade(config):
    """Archive only an unsent Assistant config; never change legacy state/queue."""
    with connection_lock(config):
        active = load_connection(config)
        if not active:
            return None
        if active['source_id'] != config.raw.get('daily_source_id'):
            raise AccessError('source_transition_required', 'La configuración activa pertenece a otra fuente; revisá la reversión.')
        database = local_db_path(config)
        if database.exists():
            with sqlite3.connect(f'file:{database.as_posix()}?mode=ro', uri=True) as conn:
                for table in ('connection_batches', 'connection_inventory_batches', 'connection_day_confirmations'):
                    exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
                    if exists and conn.execute(f'SELECT 1 FROM {table} WHERE source_id=? LIMIT 1', (active['source_id'],)).fetchone():
                        raise AccessError('rollback_review_required', 'El Asistente ya registró envíos o días confirmados. Revisá pendientes y versiones antes de volver.')
        path = connection_path(config)
        archive = config.path('state_dir') / 'legacy-migration-archive'
        archive.mkdir(parents=True, exist_ok=True)
        destination = archive / (path.stem + '-' + uuid.uuid4().hex + '.json')
        os.replace(path, destination)
        return destination
