"""Connection assistant service; all samples remain local and ephemeral."""
import json
from pathlib import Path

from .config import CollectorConfig
from .connection_config import (atomic_json, connection_path, context, digest, load_connection,
                                recommendations, save_connection, validate_profile)
from .connectors import create_connector
from .connectors.base import AccessError
from .connection_sync import build_capture, connection_lock
from .source_credentials import CredentialVault


def source_identity(config, profile):
    keys = {'files': ('folder', 'suffix'), 'sqlite': ('path', 'table'),
            'odbc': ('engine', 'server', 'database', 'schema', 'table'), 'rest': ('base_url', 'path')}[profile['kind']]
    current = load_connection(config)
    if current:
        prior = current['profile']
        if prior['kind'] != profile['kind']:
            raise AccessError('source_transition_required', 'Cambiar el tipo de fuente requiere revisar solapamientos en Backend.')
        for key in keys:
            old_value, new_value = prior.get(key), profile.get(key)
            if key in {'folder', 'path'} and profile['kind'] in {'files', 'sqlite'} and old_value and new_value:
                old_value, new_value = Path(old_value).resolve(), Path(new_value).resolve()
            if old_value != new_value:
                raise AccessError('source_transition_required', 'Cambiar de fuente requiere revisar solapamientos en Backend.')
        return current['source_id']
    legacy = config.raw.get('daily_source_id')
    if legacy:
        if (profile['kind'] == 'files' and Path(profile['folder']).resolve() == config.path('input_dir').resolve()
                and profile.get('suffix') == (config.raw.get('source_profile') or {}).get('suffix')):
            return legacy
        raise AccessError('source_transition_required', 'Ya hay una fuente RC9 vinculada. Cambiar a API u otra base requiere revisar solapamientos en Backend.')
    return 'source_' + digest([context(config), {k: profile.get(k) for k in keys}])[:40]


def preview(config, profile, mapping, window, secrets=None, *, sample=None):
    validate_profile(profile)
    if not {'fecha', 'producto_nombre', 'cantidad_vendida', 'precio_venta'} <= set(mapping):
        raise AccessError('mapping_pending', 'Confirmá fecha, producto, cantidad y precio unitario.')
    if len(set(mapping.values())) != len(mapping):
        raise AccessError('mapping_invalid', 'Cada columna puede usarse para un único dato.')
    if sample is None:
        with create_connector({**profile, 'mapping': mapping}, secrets) as reader:
            result = reader.test(window)
            sample = result['sample']
    if not sample:
        raise AccessError('sample_empty', 'Acceso correcto, pero no hay muestra para confirmar campos. Elegí un período con datos.')
    headers = sorted(sample[0])
    if any(column not in headers for column in mapping.values()):
        raise AccessError('mapping_invalid', 'El mapeo no coincide con los campos leídos.')
    from .source_setup import _conventions_for
    from .normalizer import normalize_rows, count_problem_rows
    reader_config = {**profile.get('reader', {}), 'column_mapping': mapping}
    conventions, ambiguous = _conventions_for(sample, mapping, CollectorConfig(reader_config, config.config_path), profile.get('number_format', 'auto'))
    if profile.get('number_format', 'auto') == 'auto':
        for field, frozen in profile.get('reader', {}).get('decimal_conventions', {}).items():
            if field not in mapping or frozen not in {'comma', 'dot'}:
                continue
            detected = conventions.get(field)
            if detected in {'comma', 'dot'} and detected != frozen and field not in ambiguous:
                raise AccessError('numeric_format_changed', 'El formato numérico ya no coincide con el configurado. Revisá la fuente y confirmá el formato expresamente.')
            conventions[field] = frozen
    profile = {**profile, 'mapping': mapping, 'headers': headers,
               'reader': {**reader_config, 'decimal_conventions': conventions}}
    normalized = normalize_rows(sample, CollectorConfig({**profile['reader'], 'business_timezone': profile['timezone']}, config.config_path))
    if count_problem_rows(normalized, require_dates=True):
        raise AccessError('invalid_sample', 'La muestra tiene campos inválidos. Revisá fechas, unidades, precio unitario, costos, stock y devoluciones.')
    source = source_identity(config, profile)
    old = load_connection(config)
    value = {'profile': profile, 'mapping': mapping, 'source_id': source, 'configuration_revision': (old or {}).get('configuration_revision', 0) + 1,
             'mapping_revision': digest(mapping)}
    from .connectors.base import Reading
    summary, counts = build_capture(config, value, Reading(sample, complete=False), window, 1)
    examples = []
    for raw, interpreted in zip(sample[:8], normalized.rows[:8]):
        examples.append({k: {'source': str(raw.get(v, ''))[:80], 'interpreted': str(interpreted.get(k, ''))[:80]}
                         for k, v in mapping.items()})
    return {'context': context(config), 'expected': digest(old) if old else None, 'profile': profile,
            'mapping': mapping, 'window': window, 'examples': examples, 'ambiguous': sorted(ambiguous),
            'sample_totals': summary['resumen_financiero'] if summary else {}, 'counts': counts, 'found_window': {'start': str(min(r['fecha'] for r in normalized.rows)), 'end': str(max(r['fecha'] for r in normalized.rows))}, 'signature': digest([profile, mapping, str(window.start), str(window.end)])}


def activate(config, reviewed, *, frequency=15, review_days=7, secrets=None):
    if reviewed['context'] != context(config):
        raise AccessError('stale_confirmation', 'Cambió el comercio. Volvé a configurar la fuente.')
    if reviewed['signature'] != digest([reviewed['profile'], reviewed['mapping'], str(reviewed['window'].start), str(reviewed['window'].end)]):
        raise AccessError('stale_confirmation', 'La vista previa cambió. Volvé a revisar antes de activar.')
    with connection_lock(config):
        current = load_connection(config)
        if (digest(current) if current else None) != reviewed['expected']:
            raise AccessError('stale_confirmation', 'La configuración cambió. Volvé a probar y confirmar.')
        if int(frequency) not in {15, 30, 60, 180, 360, 1440} or not 1 <= int(review_days) <= 365:
            raise AccessError('schedule_invalid', 'Revisá frecuencia y ventana de correcciones.')
        profile = reviewed['profile']
        source = source_identity(config, profile)
        if not current and config.raw.get('daily_source_id'):
            from .legacy_migration import require_migration_space
            suffix = profile.get('suffix')
            export_bytes = max((path.stat().st_size for path in Path(profile['folder']).glob('*')
                                if path.is_file() and path.suffix.lower() == suffix), default=0)
            require_migration_space(config, export_bytes=export_bytes)
        # Fail closed before activation if this identity cannot protect credentials.
        if secrets:
            CredentialVault(config, source).store(secrets)
        return save_connection(config, profile, reviewed['mapping'], reviewed['window'], frequency=frequency,
            review_days=review_days, confirmed=True, expected=reviewed['expected'], source_id=source)


def draft_path(config):
    return config.path('state_dir') / ('connection-draft-' + context(config) + '.json')


def save_draft(config, value):
    from .connection_config import reject_secrets
    reject_secrets(value)
    atomic_json(draft_path(config), {'context': context(config), 'value': value})


def load_draft(config):
    path = draft_path(config)
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    return data['value'] if data.get('context') == context(config) else {}


def detect_options(config, paths=(), *, consent=False):
    if not consent:
        raise AccessError('consent_required', 'Autorizá la inspección de rutas elegidas y nombres de conexiones ODBC.')
    options = []
    for selected in list(paths)[:10]:
        path = Path(selected)
        if path.is_dir():
            suffixes = {p.suffix.lower() for _, p in zip(range(200), path.iterdir()) if p.is_file()}
            if suffixes & {'.csv', '.xlsx'}:
                options.append({'kind': 'files', 'state': 'detected', 'label': 'Exportaciones CSV/XLSX en la carpeta seleccionada', 'confidence': 0.9,
                                'missing': 'Probar lectura, confirmar campos, cobertura y exportación automática.', 'evidence': {'read_only': True}})
        elif path.suffix.lower() in {'.db', '.sqlite', '.sqlite3'}:
            options.append({'kind': 'sqlite', 'state': 'detected', 'label': 'Archivo SQLite seleccionado', 'confidence': 0.7,
                            'missing': 'Autorización de lectura y perfil de tabla; no se comprobó el contenido.', 'evidence': {}})
    try:
        from .connectors.odbc import odbc_module
        module = odbc_module()
        drivers, dsns = module.drivers(), module.dataSources()
        for name, driver in list(dsns.items())[:30]:
            options.append({'kind': 'odbc', 'state': 'profile_required', 'label': f'DSN {name} ({driver})', 'confidence': 0.6,
                            'missing': 'Permisos de lectura y perfil SQL Server. El DSN no demuestra campos disponibles.', 'evidence': {}})
        if drivers:
            options.append({'kind': 'odbc', 'state': 'detected', 'label': 'Controladores ODBC: ' + ', '.join(drivers[:15]),
                'confidence': 0.5, 'missing': 'Identificar motor, servidor, base y tabla autorizada.', 'evidence': {}})
    except AccessError:
        options.append({'kind': 'odbc', 'state': 'driver_required', 'label': 'ODBC sin controlador utilizable', 'confidence': 0,
                        'missing': 'Instalar el controlador oficial x64 y obtener un perfil de lectura.', 'evidence': {}})
    options.append({'kind': 'rest', 'state': 'profile_required', 'label': 'API del proveedor', 'confidence': 0,
                    'missing': 'Pedir documentación, URL, autenticación, filtros de fechas, paginación y semántica de correcciones.', 'evidence': {}})
    return recommendations(options)
