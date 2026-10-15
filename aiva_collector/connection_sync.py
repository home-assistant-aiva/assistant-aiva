"""Durable daily snapshots: receipt precedes checkpoint; failed reads never enqueue partial data."""
import contextlib
import json
import os
import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .config import CollectorConfig
from .connection_config import atomic_json, context, digest, load_connection
from .connectors import create_connector
from .connectors.base import AccessError, Window, safe_error
from .local_state import connect, local_db_path, next_daily_revision
from .source_credentials import CredentialVault
from .summarizer import build_summary, idempotency_key


@contextlib.contextmanager
def connection_lock(config):
    path = config.path('state_dir') / 'connection.lock'
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        stream.seek(0)
        if path.stat().st_size == 0:
            stream.write(b'0')
            stream.flush()
        try:
            stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise AccessError('sync_busy', 'Hay una sincronización o configuración activa. Esperá y volvé a intentar.') from None
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def state_path(config):
    return config.path('state_dir') / ('connection-status-' + context(config) + '.json')


def build_capture(config, setup, reading, window, revision, *, features=(), today=None):
    from .normalizer import normalize_rows, count_problem_rows, parse_date
    profile = setup['profile']
    # Reuse RC9's parser, numeric conventions, discount semantics and identities.
    raw = {**config.raw, **profile.get('reader', {}), 'column_mapping': setup['mapping'],
           'source_schema_version': '2.0.0', 'daily_source_id': setup['source_id'],
           'business_timezone': profile['timezone'], 'daily_snapshot_complete': reading.complete,
           'daily_complete_file_sha256': None, 'source_profile': {'context': 'connection-assistant'},
           'max_products_per_summary': 200000}
    if reading.rows and profile.get('headers') and any(sorted(row) != profile['headers'] for row in reading.rows):
        raise AccessError('structure_changed', 'Los campos cambiaron. Revisá el mapeo antes de continuar.')
    source_rows = reading.rows
    if profile.get('identity_fields'):
        seen = set()
        for row in source_rows:
            identity = tuple(str(row.get(field, '')) for field in profile['identity_fields'])
            if any(not value for value in identity) or identity in seen:
                raise AccessError('operation_identity_invalid', 'Hay operaciones/líneas repetidas o sin identificador. Revisá la paginación y el perfil.')
            seen.add(identity)
    if profile.get('status_column'):
        column = profile['status_column']
        accepted, cancelled = set(profile['accepted_values']), set(profile['cancelled_values'])
        if any(row.get(column) not in accepted | cancelled for row in source_rows):
            raise AccessError('operation_status_unknown', 'Apareció un estado de operación no confirmado. Revisá anulaciones y devoluciones con el proveedor.')
        source_rows = [row for row in source_rows if row.get(column) in accepted]
    normalized = normalize_rows(source_rows, CollectorConfig(raw, config.config_path))
    if count_problem_rows(normalized, require_dates=True):
        raise AccessError('invalid_rows', 'Hay filas con fechas, cantidades, devoluciones, costos o importes inválidos. Revisá el perfil; no se enviaron totales parciales.')
    if any(r.get('stock_actual') is not None and r['stock_actual'] < 0 for r in normalized.rows):
        raise AccessError('negative_stock', 'El origen informó stock negativo. Revisá su significado con el proveedor antes de usarlo.')
    selected, outside = [], reading.outside
    for row in normalized.rows:
        if window.start <= row['fecha'] <= window.end:
            selected.append(row)
        else:
            outside += 1
    if not selected:
        if not reading.empty_confirmed or not reading.complete:
            return None, {'inside': 0, 'outside': outside, 'coverage': 'unknown'}
        if 'empty_daily' not in features:
            raise AccessError('backend_upgrade_required', 'Este Backend no confirma días vacíos sin productos; se necesita el candidato Backend RC10.')
        summary = {'commerce_id': config.commerce_id, 'collector_id': config.collector_id,
                   'periodo': 'daily', 'fecha_inicio': str(window.start), 'fecha_fin': str(window.end),
                   'productos_resumidos': [], 'resumen_financiero': {}, 'metadata': {},
                   'collector_version': config.collector_version, 'source_schema_version': '2.0.0',
                   'daily_snapshot': {'source_id': setup['source_id'], 'revision': revision, 'timezone': profile['timezone'],
                       'semantics': 'snapshot_replace', 'price_semantics': 'final_net', 'scope': 'whole_commerce',
                       'completeness_declared': True, 'currency': profile.get('currency'),
                       'coverage': [{'business_date': str(window.start), 'status': 'complete'}], 'metrics': []}}
    else:
        summary = build_summary(selected, CollectorConfig(raw, config.config_path), 1, len(selected), 0)
        snapshot = summary['daily_snapshot']
        snapshot['revision'] = revision
        by_key = {}
        from .daily import stable_product_code
        for row in selected:
            by_key.setdefault((str(row['fecha']), stable_product_code(row)), []).append(row)
        for metric in snapshot['metrics']:
            group = by_key[(metric['business_date'], metric['product_code'])]
            if 'dated_stock' in features and metric['closing_stock'] is not None and all(r.get('fecha_stock') == r['fecha'] for r in group):
                metric['stock_as_of_date'] = metric['business_date']
            if profile.get('cost_basis', 'unknown') != 'historical':
                metric['unit_cost'] = metric['cogs'] = None
                if 'cost_missing' not in metric['quality_flags']:
                    metric['quality_flags'].append('cost_missing')
            if 'cost_basis' in features:
                metric['cost_basis'] = profile.get('cost_basis', 'unknown')
        if profile.get('cost_basis', 'unknown') != 'historical':
            for product in summary['productos_resumidos']:
                for name in ('costo_total_estimado', 'costo_unitario_promedio', 'margen_bruto_estimado', 'margen_porcentaje_estimado'):
                    product[name] = None
            summary['resumen_financiero'] = {'cost_basis': profile.get('cost_basis', 'unknown'), 'limitations': ['historical_cost_unavailable']}
    snapshot = summary['daily_snapshot']
    today = today or datetime.now(ZoneInfo(profile['timezone'])).date()
    for coverage in snapshot['coverage']:
        if date.fromisoformat(coverage['business_date']) >= today:
            coverage['status'] = 'partial'
    summary['metadata'].update({'connection': {'configuration_revision': setup['configuration_revision'],
        'mapping_revision': setup['mapping_revision'], 'source_id': setup['source_id'], 'kind': profile['kind'],
        'requested_start': str(window.start), 'requested_end': str(window.end), 'rows_inside': len(selected),
        'rows_outside': outside, 'cost_basis': profile.get('cost_basis', 'unknown')}})
    return summary, {'inside': len(selected), 'outside': outside, 'coverage': snapshot['coverage']}


def _init(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS connection_batches (
        context TEXT NOT NULL, source_id TEXT NOT NULL, capture_key TEXT NOT NULL,
        payload_json TEXT NOT NULL, idempotency_key TEXT NOT NULL, status TEXT NOT NULL,
        confirmed_at TEXT, PRIMARY KEY(context,source_id,capture_key))''')
    conn.commit()


def synchronize(config, *, force=False, client=None, connector=None, now=None):
    from .client import CollectorClient
    from .errors import BackendError
    setup = load_connection(config)
    if not setup:
        raise AccessError('configuration_incomplete', 'Abrí el asistente de conexión.')
    if setup.get('paused'):
        return {'state': 'paused', 'message': 'La fuente está pausada.', 'sent': 0}
    status = json.loads(state_path(config).read_text()) if state_path(config).exists() else {}
    clock = now or datetime.now(timezone.utc)
    same_revision = status.get('configuration_revision') == setup['configuration_revision']
    if not force and same_revision and status.get('state') == 'intervention_required':
        return status
    if not force and same_revision and clock.timestamp() < status.get('next_attempt', 0):
        return status
    if setup['profile']['kind'] == 'sqlite':
        from pathlib import Path
        if Path(setup['profile']['path']).resolve() == local_db_path(config).resolve():
            raise AccessError('internal_database_forbidden', 'La SQLite interna de AIVA no es una fuente comercial.')
    config.require_send_ready()
    if not config.backend_url.startswith('https://'):
        raise AccessError('tls_required', 'Configurá un Backend HTTPS válido antes de sincronizar datos del comercio.')
    with connection_lock(config):
        conn = connect(local_db_path(config))
        _init(conn)
        client = client or CollectorClient(config)
        binding = context(config)
        sent, duplicates, units = 0, 0, 0
        started = time.monotonic()
        result = {'state': 'sync_completed', 'sent': 0, 'duplicates': 0, 'code': None, 'requested_window': setup['window'], 'complete_dates': [], 'partial_dates': [], 'missing_dates': []}
        try:
            # Existing RC9 pending payloads retain their payload and idempotency.
            # Never abandon them when enabling the new connection workflow.
            from .offline_queue import process_queue
            legacy = process_queue(conn, config, client=client)
            if legacy.errors:
                raise AccessError('legacy_queue_intervention', 'Hay envíos RC9 rechazados. Revisá la cola antes de continuar.')
            service = client.service_status()
            features = service.get('ingestion_features', [])
            result['capabilities'] = service.get('decision_readiness', {}).get('capabilities', [])
            # Deliver durable pending payloads before creating captures. No credential
            # or source access is necessary for recovery of an already read batch.
            def deliver(key, payload, idem):
                nonlocal sent, duplicates
                if digest(load_connection(config)) != digest(setup):
                    raise AccessError('configuration_changed', 'La fuente cambió durante la sincronización; revisá y reanudá.')
                try:
                    client.send_summary(payload)
                    sent += 1
                except BackendError as exc:
                    if exc.status_code != 409:
                        if exc.status_code is None or exc.status_code == 429 or exc.status_code >= 500:
                            raise AccessError('backend_temporary', 'AIVA no confirmó la recepción. El envío queda pendiente.', retry_after=60) from None
                        raise AccessError('backend_rejected', 'AIVA rechazó el envío. Revisá activación, contrato y permisos antes de reanudar.') from None
                    duplicates += 1
                conn.execute("UPDATE connection_batches SET status='sent',confirmed_at=? WHERE context=? AND source_id=? AND capture_key=?", (clock.isoformat(), binding, setup['source_id'], key))
                conn.commit()
                result['last_success'] = clock.isoformat()
            pending = conn.execute("SELECT * FROM connection_batches WHERE context=? AND source_id=? AND status='pending'", (binding, setup['source_id'])).fetchall()
            for batch in pending:
                deliver(batch['capture_key'], json.loads(batch['payload_json']), batch['idempotency_key'])
            until = date.fromisoformat(setup['window']['end'])
            since = date.fromisoformat(setup['window']['start'])
            today = clock.astimezone(ZoneInfo(setup['profile']['timezone'])).date()
            last_closed = today - timedelta(days=1)
            # Initial captures missing from this configuration, then configurable
            # recent full-day recaptures. Each day is an independent recovery unit.
            history_days = [since + timedelta(days=i) for i in range((until-since).days+1)]
            recent_days = [last_closed - timedelta(days=i) for i in reversed(range(setup['review_days']))]
            days = sorted(set(history_days + recent_days))
            vault = CredentialVault(config, setup['source_id'])
            owned = connector is None
            if connector is None:
                secrets = vault.load()
                connector = create_connector(setup['profile'], secrets,
                    **({'refreshed': vault.store} if setup['profile']['kind'] == 'rest' else {}))
            try:
                for day in days:
                    if time.monotonic() - started > 240:
                        result['state'] = 'ready'
                        result['message'] = 'Avance guardado; la próxima ejecución continuará.'
                        break
                    window = Window(day, day)
                    # Old historical days need reading once per configuration revision.
                    work_key = digest([setup['configuration_revision'], str(day)])
                    prior = conn.execute("SELECT status FROM connection_batches WHERE context=? AND source_id=? AND capture_key=?", (binding, setup['source_id'], work_key)).fetchone()
                    if prior and day not in recent_days:
                        continue
                    reading = connector.read(window)
                    payload, counts = build_capture(config, setup, reading, window, next_daily_revision(conn), features=features, today=today)
                    units += counts['inside']
                    if payload is None:
                        result['missing_days'] = result.get('missing_days', 0) + 1
                        result['missing_dates'].append(str(day))
                        continue
                    for coverage in payload['daily_snapshot']['coverage']:
                        result['complete_dates' if coverage['status'] == 'complete' else 'partial_dates'].append(coverage['business_date'])
                    result['last_read_counts'] = counts
                    idem = idempotency_key(payload)
                    # Same content has the same key, regardless of revision/config range.
                    previous = conn.execute("SELECT status FROM connection_batches WHERE context=? AND source_id=? AND idempotency_key=? AND status='sent'", (binding, setup['source_id'], idem)).fetchone()
                    if previous:
                        duplicates += 1
                        # Mark this historical work unit too, without another delivery.
                        state = 'sent'
                    else:
                        state = 'pending'
                    conn.execute("INSERT OR REPLACE INTO connection_batches VALUES (?,?,?,?,?,?,?)", (binding, setup['source_id'], work_key, json.dumps(payload), idem, state, clock.isoformat() if previous else None))
                    conn.commit()
                    if not previous:
                        deliver(work_key, payload, idem)
            finally:
                if owned and connector is not None:
                    connector.close()
            refreshed_status = client.service_status()
            result['capabilities'] = refreshed_status.get('decision_readiness', {}).get('capabilities', [])
            result['retry_count'] = 0
            result['message'] = result.get('message', 'Sincronización finalizada. Revisá cobertura y funciones informadas por AIVA.')
            result['next_attempt'] = clock.timestamp() + setup['frequency_minutes'] * 60
        except Exception as exc:
            error = safe_error(exc)
            retries = int(status.get('retry_count', 0)) + 1 if same_revision else 1
            result['retry_count'] = retries
            result.update(state='intervention_required' if not error['retry_after'] or retries > 10 else 'ready', **error,
                          next_attempt=clock.timestamp() + (error['retry_after'] or 86400))
        finally:
            conn.close()
        result.update(sent=sent, duplicates=duplicates, rows=units, finished_at=clock.isoformat(), source_id=setup['source_id'],
                      configuration_revision=setup['configuration_revision'], version=config.collector_version,
                      last_success=result.get('last_success', status.get('last_success')))
        atomic_json(state_path(config), result)
        return result
