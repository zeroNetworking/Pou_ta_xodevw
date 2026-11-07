import csv
import io
from datetime import date
from conftest import make_closed_month


def test_all_pages_render(api, raw_db):
    mid = api.new_month()
    api.add(mid, description='καφές')
    user_id = raw_db.execute("SELECT id FROM users").fetchone()[0]
    closed = make_closed_month(raw_db, user_id)
    t = date.today()
    for url in ['/', '/analytics', '/calendar', f'/calendar/{t.year}/{t.month}', '/calendar/1999/13',
                '/profile', f'/month/{mid}', f'/month/{closed}', '/search', '/search?q=καφ']:
        r = api.client.get(url)
        assert r.status_code in (200, 302), url


def test_empty_dashboard(api):
    assert api.client.get('/').status_code == 200
    assert api.client.get('/analytics').status_code == 200


def test_search(api):
    mid = api.new_month()
    api.add(mid, description='καφές με Γιώργο')
    api.add(mid, description='100% βενζίνη')
    api.add(mid, description='άλλο')
    body = api.client.get('/search?q=καφές').get_data(as_text=True)
    assert '1 αποτελέσματα' in body
    # % is literal, not a wildcard
    assert '1 αποτελέσματα' in api.client.get('/search?q=%25').get_data(as_text=True)


def test_search_isolated_per_user(api, other_api):
    mid = api.new_month()
    api.add(mid, description='μυστικό')
    assert '0 αποτελέσματα' in other_api.client.get('/search?q=μυστικό').get_data(as_text=True)


def _rows(resp):
    text = resp.get_data(as_text=True).lstrip('﻿')
    return list(csv.reader(io.StringIO(text)))


def test_month_csv_export_and_formula_injection(api):
    mid = api.new_month()
    api.add(mid, amount=10, description='=HYPERLINK("http://evil","x")')
    api.add(mid, type='income', category='Μισθός', subcategory='', amount=100)
    r = api.client.get(f'/export/month/{mid}/csv')
    assert r.status_code == 200
    assert "filename*=UTF-8''" in r.headers['Content-Disposition']
    rows = _rows(r)
    descs = [row[5] for row in rows[1:3]]
    assert "'=HYPERLINK(\"http://evil\",\"x\")" in descs
    assert ['Υπόλοιπο', '', '', '', '90.00', '', '', ''] in rows


def test_multi_month_csv(api, raw_db):
    mid = api.new_month()
    api.add(mid, amount=7)
    r = api.client.get(f'/export/year/csv?month_ids={mid},{mid}')
    assert r.status_code == 200
    assert ['Σύνολο Εξόδων', '', '', '', '', '7.00', ''] in _rows(r)
    assert api.client.get('/export/year/csv?month_ids=a,b').status_code == 400
    assert api.client.get('/export/year/csv').status_code == 400


def test_pdf_export(api):
    mid = api.new_month()
    api.add(mid, amount=12.34, description='Ελληνικά άέήίόύώ')
    api.post('/fixed_expenses', {'label': 'ΔΕΗ', 'amount': 50, 'category': 'Σπίτι & Λογαριασμοί'})
    r = api.client.get(f'/export/month/{mid}/pdf')
    assert r.status_code == 200
    assert r.data[:4] == b'%PDF'


def test_pdf_export_empty_month(api):
    mid = api.new_month()
    r = api.client.get(f'/export/month/{mid}/pdf')
    assert r.status_code == 200 and r.data[:4] == b'%PDF'


def test_month_page_date_bounds(api):
    mid = api.new_month()
    html = api.client.get(f'/month/{mid}').get_data(as_text=True)
    t = date.today()
    assert f'const MONTH_MIN_DATE = "{date(t.year, t.month, 1).isoformat()}"' in html
    assert f'const DEFAULT_DATE   = "{t.isoformat()}"' in html


def test_analytics_year_buttons_are_dynamic(api):
    api.new_month()
    html = api.client.get('/analytics').get_data(as_text=True)
    assert f'selectExportYear({date.today().year})' in html
    assert 'selectExportYear(2024)' not in html or date.today().year == 2024


def test_api_now_is_public(client):
    r = client.get('/api/now')
    assert r.status_code == 200 and 'time' in r.get_json()
