from datetime import date, timedelta
import pytest
from conftest import make_closed_month


def test_add_transaction_updates_stats(api):
    mid = api.new_month()
    assert api.add(mid, amount=12.5).get_json()['success']
    assert api.add(mid, type='income', category='Μισθός', subcategory='', amount=1000).get_json()['success']
    s = api.stats(mid)
    assert s['total_income'] == 1000 and s['total_expense'] == 12.5 and s['balance'] == 987.5


@pytest.mark.parametrize('payload,field', [
    ({'amount': 'inf'}, 'amount'),
    ({'amount': 'nan'}, 'amount'),
    ({'amount': -5}, 'amount'),
    ({'amount': 0}, 'amount'),
    ({'amount': True}, 'amount'),
    ({'amount': 'abc'}, 'amount'),
    ({'amount': 1e12}, 'amount'),
    ({'category': 123}, 'category'),
    ({'category': ''}, 'category'),
    ({'category': 'Δεν υπάρχει'}, 'category'),
    ({'type': 'income', 'category': 'Σούπερ Μάρκετ'}, 'category'),
    ({'subcategory': 'Βενζίνη'}, 'subcategory'),
    ({'type': 'gift'}, 'type'),
    ({'date': 'garbage'}, 'date'),
    ({'date': '2020-01-01'}, 'date'),
    ({'description': 'x' * 501}, 'description'),
    ({'description': ['list']}, 'description'),
    ({'late_entry': 'abc', 'amount': 'nan'}, 'amount'),
])
def test_add_transaction_rejects_bad_input(api, payload, field):
    mid = api.new_month()
    r = api.add(mid, **payload)
    assert r.status_code == 400, (payload, r.get_json())
    assert api.stats(mid)['total_expense'] == 0


def test_add_transaction_bad_month_id(api):
    for bad in ['abc', None, [1], 99999]:
        r = api.post('/add_transaction', {'month_id': bad, 'category': 'Σούπερ Μάρκετ', 'amount': 1})
        assert r.status_code in (400, 404), bad


def test_non_json_body_is_400_not_500(api):
    r = api.client.post('/add_transaction', data='not json',
                        headers={'X-CSRF-Token': api.token, 'Content-Type': 'application/json'})
    assert r.status_code == 400
    r = api.post('/add_transaction', json=['a', 'list'])
    assert r.status_code == 400


def test_date_defaults_to_inside_month(api, raw_db):
    t = date.today()
    nxt = date(t.year + (t.month == 12), t.month % 12 + 1, 1)
    mid = api.new_month(nxt.year, nxt.month)
    tid = api.add(mid).get_json()['id']
    row = raw_db.execute("SELECT transaction_date FROM transactions WHERE id=?", (tid,)).fetchone()
    assert row[0] == nxt.isoformat()


def test_edit_transaction(api, raw_db):
    mid = api.new_month()
    tid = api.add(mid).get_json()['id']
    r = api.put(f'/edit_transaction/{tid}', {
        'type': 'income', 'category': 'Μισθός', 'amount': '55.556', 'date': date.today().isoformat()})
    assert r.get_json()['success']
    row = raw_db.execute("SELECT * FROM transactions WHERE id=?", (tid,)).fetchone()
    assert row['type'] == 'income' and row['amount'] == 55.56 and row['subcategory'] == ''


def test_edit_rejects_nan_without_500(api):
    mid = api.new_month()
    tid = api.add(mid).get_json()['id']
    r = api.put(f'/edit_transaction/{tid}', {'category': 'Σούπερ Μάρκετ', 'amount': 'nan'})
    assert r.status_code == 400


def test_delete_transaction(api):
    mid = api.new_month()
    tid = api.add(mid).get_json()['id']
    assert api.delete(f'/delete_transaction/{tid}').get_json()['success']
    assert api.stats(mid)['total_expense'] == 0


def test_cannot_touch_other_users_data(api, other_api):
    mid = api.new_month()
    tid = api.add(mid).get_json()['id']
    assert other_api.add(mid).status_code == 404
    assert other_api.put(f'/edit_transaction/{tid}', {'category': 'Σούπερ Μάρκετ', 'amount': 1}).status_code == 404
    assert other_api.delete(f'/delete_transaction/{tid}').status_code == 404
    assert other_api.delete(f'/delete_month/{mid}').status_code == 404
    assert other_api.post(f'/close_month/{mid}').status_code == 404
    assert other_api.client.get(f'/api/month_stats/{mid}').status_code == 404
    assert other_api.client.get(f'/export/month/{mid}/csv').status_code == 302
    assert api.stats(mid)['total_expense'] == 10


def test_closed_month_is_read_only(api, raw_db):
    mid = api.new_month()
    tid = api.add(mid).get_json()['id']
    assert api.post(f'/close_month/{mid}').get_json()['success']
    assert api.add(mid).status_code == 403
    assert api.put(f'/edit_transaction/{tid}', {'category': 'Σούπερ Μάρκετ', 'amount': 1}).status_code == 403
    assert api.delete(f'/delete_transaction/{tid}').status_code == 403


def test_closing_twice_keeps_closed_at(api, raw_db):
    mid = api.new_month()
    api.post(f'/close_month/{mid}')
    first = raw_db.execute("SELECT closed_at FROM months WHERE id=?", (mid,)).fetchone()[0]
    api.post(f'/close_month/{mid}')
    assert raw_db.execute("SELECT closed_at FROM months WHERE id=?", (mid,)).fetchone()[0] == first


def test_late_entry(api, raw_db):
    user_id = raw_db.execute("SELECT id FROM users").fetchone()[0]
    closed = make_closed_month(raw_db, user_id, 2020, 2)
    # Date must be inside the closed month (2020 is a leap year)
    r = api.add(closed, late_entry=1, date='2020-02-29', late_entry_note='ξεχασμένο')
    assert r.get_json()['success'], r.get_json()
    r = api.add(closed, late_entry=1, date=date.today().isoformat())
    assert r.status_code == 400
    # late_entry flag on an OPEN month is rejected
    mid = api.new_month()
    assert api.add(mid, late_entry=1).status_code == 400


def test_past_month_cannot_be_created(api):
    r = api.post('/new_month', {'year': 2020, 'month': 1})
    assert r.status_code == 400
    r = api.post('/new_month', {'year': 'x', 'month': 1})
    assert r.status_code == 400


def test_duplicate_month(api):
    mid = api.new_month()
    t = date.today()
    r = api.post('/new_month', {'year': t.year, 'month': t.month})
    assert r.status_code == 409 and r.get_json()['month_id'] == mid


def test_delete_month_removes_children(api, raw_db):
    mid = api.new_month()
    api.add(mid)
    assert api.delete(f'/delete_month/{mid}').get_json()['success']
    assert raw_db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0


def test_expired_months_auto_close(api, raw_db):
    user_id = raw_db.execute("SELECT id FROM users").fetchone()[0]
    raw_db.execute("INSERT INTO months (user_id, year, month, name) VALUES (?, 2021, 5, 'Μάιος 2021')", (user_id,))
    raw_db.commit()
    with api.client.session_transaction() as s:
        s.pop('last_close_check', None)
    api.client.get('/')
    row = raw_db.execute("SELECT is_closed, closed_at FROM months WHERE year=2021").fetchone()
    assert row['is_closed'] == 1 and row['closed_at'].startswith('2021-05-31')


def test_add_transaction_rate_limit(api):
    mid = api.new_month()
    codes = [api.add(mid, amount=1).status_code for _ in range(61)]
    assert codes[:60] == [200] * 60
    assert codes[60] == 429
