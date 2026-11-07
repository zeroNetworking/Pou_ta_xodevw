"""
Shared pytest fixtures.

Every test gets a fresh SQLite database in a temp dir and a clean
rate limiter, so tests are independent and can run in any order.
"""

import os
import re
import sys
import sqlite3
import tempfile
from datetime import date

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Must be set before `app` is imported (it initialises the DB and the log file)
_tmp = tempfile.mkdtemp(prefix='finance-tests-')
os.environ['DATABASE_PATH'] = os.path.join(_tmp, 'bootstrap.db')
os.environ['LOG_PATH']      = os.path.join(_tmp, 'test.log')
os.environ.setdefault('SECRET_KEY', 'test-secret-key')
os.environ.pop('PRODUCTION', None)

import app as app_module            # noqa: E402
from services import db as db_module, rate_limit  # noqa: E402

PASSWORD = 'Passw0rd!'


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = str(tmp_path / 'test.db')
    monkeypatch.setattr(db_module, 'DB_PATH', path)
    db_module.init_db()
    return path


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    rate_limit._rate_attempts.clear()
    yield
    rate_limit._rate_attempts.clear()


@pytest.fixture
def app(db_path):
    app_module.app.config.update(TESTING=True)
    return app_module.app


@pytest.fixture
def raw_db(db_path):
    """Direct DB connection for arranging state / asserting on rows."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def form_csrf(client, url):
    html = client.get(url).get_data(as_text=True)
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert m, f'no csrf token on {url}'
    return m.group(1)


class Api:
    """Small helper around the test client for JSON endpoints with CSRF."""

    def __init__(self, client):
        self.client = client
        self.token = client.get('/api/csrf_token').get_json()['csrf_token']

    def _h(self):
        return {'X-CSRF-Token': self.token}

    def post(self, url, json=None):
        return self.client.post(url, json=json or {}, headers=self._h())

    def put(self, url, json=None):
        return self.client.put(url, json=json or {}, headers=self._h())

    def delete(self, url):
        return self.client.delete(url, headers=self._h())

    def new_month(self, year=None, month=None):
        t = date.today()
        r = self.post('/new_month', {'year': year or t.year, 'month': month or t.month})
        assert r.status_code == 200, r.get_json()
        return r.get_json()['month_id']

    def add(self, month_id, **kw):
        body = {'month_id': month_id, 'type': 'expense',
                'category': 'Σούπερ Μάρκετ', 'subcategory': 'Τρόφιμα', 'amount': 10}
        body.update(kw)
        return self.post('/add_transaction', body)

    def stats(self, month_id):
        return self.client.get(f'/api/month_stats/{month_id}').get_json()


def register(client, username='testuser1', password=PASSWORD, answer='rex'):
    token = form_csrf(client, '/register')
    return client.post('/register', data={
        'csrf_token': token, 'username': username, 'password': password,
        'confirm': password, 'recovery_question': app_module.RECOVERY_QUESTIONS[0],
        'recovery_answer': answer,
    })


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def api(app):
    c = app.test_client()
    r = register(c)
    assert r.status_code == 302
    return Api(c)


@pytest.fixture
def other_api(app):
    c = app.test_client()
    assert register(c, username='otheruser1').status_code == 302
    return Api(c)


def make_closed_month(raw_db, user_id, year=2020, month=3):
    cur = raw_db.execute(
        "INSERT INTO months (user_id, year, month, name, is_closed, closed_at) VALUES (?,?,?,?,1,?)",
        (user_id, year, month, f'Test {month}/{year}', f'{year}-{month:02d}-28T23:59:59')
    )
    raw_db.commit()
    return cur.lastrowid
