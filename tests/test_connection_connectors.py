import json
import os
import sqlite3
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from aiva_collector.connectors.base import AccessError, Window
from aiva_collector.connectors.rest import RESTConnector
from aiva_collector.connectors.sqlite import SQLiteConnector

DAY = Window(date(2026, 10, 1), date(2026, 10, 1))


@pytest.fixture
def api():
    calls = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            from urllib.parse import parse_qs, urlsplit
            parsed = urlsplit(self.path)
            calls.append((parsed.path, parse_qs(parsed.query), self.headers.get('Authorization')))
            if self.headers.get('Authorization') != 'Bearer synthetic-only':
                self.send_response(401); self.end_headers(); return
            status = 200
            if parsed.path == '/direct':
                data = [{'date': '2026-10-01', 'name': 'Producto', 'qty': 2, 'price': 10}]
            elif parsed.path == '/nested':
                cursor = parse_qs(parsed.query).get('cursor', [''])[0]
                data = {'data': {'items': [{'sale': {'day': '2026-10-01', 'name': 'Producto ' + (cursor or 'A')}, 'q': 1, 'p': 10}], 'cursor': 'B' if not cursor else None}}
            elif parsed.path == '/cross':
                data = {'rows': [{'date': '2026-10-01'}], 'next': 'https://different.invalid/steal'}
            elif parsed.path == '/loop':
                data = {'rows': [{'date': '2026-10-01'}], 'cursor': 'again'}
            elif parsed.path == '/rate':
                self.send_response(429); self.send_header('Retry-After', '75'); self.end_headers(); return
            else:
                status, data = 403, {}
            self.send_response(status); self.send_header('Content-Type', 'application/json'); self.end_headers()
            self.wfile.write(json.dumps(data).encode())
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{server.server_port}', calls
    server.shutdown(); server.server_close(); thread.join()


def profile(url, path='/direct'):
    return {'kind': 'rest', 'base_url': url, 'path': path, 'auth': 'bearer', 'semantics': 'whole_day_snapshot',
        'date_filters': {'from': 'from', 'to': 'to'}, 'fields': {'fecha': 'date', 'producto': 'name', 'cantidad': 'qty', 'precio': 'price'},
        'complete_days': True}


def test_real_http_two_structures_and_cursor(api):
    url, calls = api
    with RESTConnector(profile(url), {'access_token': 'synthetic-only'}, allow_loopback=True) as connector:
        assert connector.read(DAY).rows[0]['cantidad'] == 2
        assert connector.read(DAY).rows[0]['cantidad'] == 2  # no page state leak
    p = profile(url, '/nested')
    p.update(items_path='data.items', fields={'fecha': 'sale.day', 'producto': 'sale.name', 'cantidad': 'q', 'precio': 'p'},
             pagination={'mode': 'cursor', 'parameter': 'cursor', 'next_path': 'data.cursor'})
    with RESTConnector(p, {'access_token': 'synthetic-only'}, allow_loopback=True) as connector:
        result = connector.read(DAY)
    assert len(result.rows) == 2
    assert result.complete
    assert calls[0][1] == {'from': ['2026-10-01'], 'to': ['2026-10-01']}


def test_auth_rate_limit_and_no_domain_credentials(api):
    url, calls = api
    with RESTConnector(profile(url), {'access_token': 'wrong'}, allow_loopback=True) as connector:
        with pytest.raises(AccessError, match='Credenciales'):
            connector.read(DAY)
    p = profile(url, '/rate')
    with RESTConnector(p, {'access_token': 'synthetic-only'}, allow_loopback=True) as connector:
        with pytest.raises(AccessError) as caught:
            connector.read(DAY)
        assert caught.value.retry_after == 75
    p = profile(url, '/cross')
    p.update(items_path='rows', fields={'fecha': 'date'}, pagination={'mode': 'next_link', 'next_path': 'next'})
    with RESTConnector(p, {'access_token': 'synthetic-only'}, allow_loopback=True) as connector:
        with pytest.raises(AccessError) as caught:
            connector.read(DAY)
        assert caught.value.code == 'origin_changed'
    assert all(x[0] != '/steal' for x in calls)


def test_pagination_loop_and_remote_http_blocked(api):
    url, _ = api
    p = profile(url, '/loop')
    p.update(items_path='rows', fields={'fecha': 'date'}, pagination={'mode': 'cursor', 'parameter': 'cursor', 'next_path': 'cursor'})
    with RESTConnector(p, {'access_token': 'synthetic-only'}, allow_loopback=True) as connector:
        with pytest.raises(AccessError) as caught:
            connector.read(DAY)
        assert caught.value.code == 'pagination_loop'
    with pytest.raises(AccessError):
        RESTConnector(profile('http://example.com'))


def test_sqlite_real_read_only_wal_and_query_bounds(tmp_path):
    path = tmp_path / 'business.sqlite'
    writer = sqlite3.connect(path)
    writer.execute('PRAGMA journal_mode=WAL')
    writer.execute('CREATE TABLE sales(day TEXT, product TEXT, qty INTEGER, price INTEGER)')
    writer.executemany('INSERT INTO sales VALUES(?,?,?,?)', [('2026-10-01', 'Producto', 2, 10), ('2026-09-30', 'Anterior', 1, 10)])
    writer.commit()
    p = {'kind': 'sqlite', 'path': str(path), 'table': 'sales', 'date_column': 'day', 'columns': ['day', 'product', 'qty', 'price'], 'complete_days': True}
    with SQLiteConnector(p) as reader:
        assert reader.read(DAY).rows == [{'day': '2026-10-01', 'product': 'Producto', 'qty': 2, 'price': 10}]
    assert writer.execute('SELECT count(*) FROM sales').fetchone()[0] == 2
    with pytest.raises(AccessError):
        SQLiteConnector({**p, 'table': 'sales; DELETE FROM sales'}).read(DAY)
    writer.execute('CREATE VIEW dangerous AS SELECT load_extension("bad")')
    writer.commit()
    with pytest.raises(AccessError):
        SQLiteConnector({**p, 'table': 'dangerous'}).read(DAY)
    with pytest.raises(AccessError) as caught:
        SQLiteConnector({**p, 'max_rows': 1, 'date_column': 'day'}).read(Window(date(2026,9,1), date(2026,10,1)))
    assert caught.value.code == 'row_limit'
    writer.close()


@pytest.mark.skipif(not os.environ.get('AIVA_TEST_SQLSERVER_PROFILE'), reason='Requires authorized synthetic SQL Server + official ODBC driver')
def test_real_sqlserver_read_only_profile():
    from aiva_collector.connectors.odbc import SQLServerConnector
    p = json.loads(open(os.environ['AIVA_TEST_SQLSERVER_PROFILE'], encoding='utf-8').read())
    credentials = {'username': os.environ.get('AIVA_TEST_SQLSERVER_USER'), 'password': os.environ.get('AIVA_TEST_SQLSERVER_PASSWORD')}
    with SQLServerConnector(p, credentials) as reader:
        result = reader.read(DAY)
        assert result.rows and set(p['columns']) == set(result.rows[0])
