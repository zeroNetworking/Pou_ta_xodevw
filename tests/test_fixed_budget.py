from datetime import date
from conftest import make_closed_month

RENT = {'label': "Rent's \"flat\" <b>", 'amount': 400, 'category': 'Σπίτι & Λογαριασμοί'}


def _fixed(api, **kw):
    body = dict(RENT); body.update(kw)
    r = api.post('/fixed_expenses', body)
    assert r.status_code == 200, r.get_json()
    return r.get_json()['id']


def _pay(api, fid, mid, paid):
    return api.post('/fixed_payment', {'fixed_expense_id': fid, 'month_id': mid, 'paid': paid})


def test_marking_paid_twice_does_not_duplicate(api):
    mid, fid = api.new_month(), None
    fid = _fixed(api)
    assert _pay(api, fid, mid, 1).get_json()['success']
    assert _pay(api, fid, mid, 1).get_json()['success']
    assert api.stats(mid)['total_expense'] == 400


def test_unpaid_removes_only_its_own_transaction(api):
    mid = api.new_month()
    fid = _fixed(api)
    # A manual transaction that looks identical to the auto one must survive
    api.add(mid, category='Σπίτι & Λογαριασμοί', subcategory='Ενοίκιο',
            amount=400, description=f"[Σταθερό] {RENT['label']}")
    _pay(api, fid, mid, 1)
    assert api.stats(mid)['total_expense'] == 800
    _pay(api, fid, mid, 0)
    assert api.stats(mid)['total_expense'] == 400


def test_unpaid_after_amount_edit_still_removes_transaction(api):
    mid = api.new_month()
    fid = _fixed(api)
    _pay(api, fid, mid, 1)
    assert api.put(f'/fixed_expenses/{fid}', dict(RENT, amount=450)).get_json()['success']
    _pay(api, fid, mid, 0)
    assert api.stats(mid)['total_expense'] == 0


def test_deleting_auto_transaction_unmarks_payment(api, raw_db):
    mid = api.new_month()
    fid = _fixed(api)
    _pay(api, fid, mid, 1)
    tid = raw_db.execute("SELECT id FROM transactions").fetchone()[0]
    api.delete(f'/delete_transaction/{tid}')
    paid = raw_db.execute("SELECT paid FROM fixed_payments WHERE fixed_expense_id=?", (fid,)).fetchone()[0]
    assert paid == 0
    # and paying again works (no stale state)
    _pay(api, fid, mid, 1)
    assert api.stats(mid)['total_expense'] == 400


def test_fixed_without_amount_creates_no_transaction(api):
    mid = api.new_month()
    fid = _fixed(api, amount=0)
    _pay(api, fid, mid, 1)
    assert api.stats(mid)['total_expense'] == 0


def test_fixed_payment_bad_input(api, raw_db):
    mid = api.new_month()
    fid = _fixed(api)
    assert _pay(api, fid, mid, 'xyz').status_code == 200   # falls back to "paid", no 500
    assert _pay(api, 'abc', mid, 1).status_code == 400
    assert _pay(api, fid, 99999, 1).status_code == 404
    user_id = raw_db.execute("SELECT id FROM users").fetchone()[0]
    closed = make_closed_month(raw_db, user_id)
    assert _pay(api, fid, closed, 1).status_code == 403


def test_fixed_expense_validation(api):
    for bad in [{'label': ''}, {'label': 'x' * 101}, {'label': 5}, {'amount': 'inf'},
                {'amount': -1}, {'category': 'Άγνωστη'}]:
        body = dict(RENT); body.update(bad)
        assert api.post('/fixed_expenses', body).status_code == 400, bad


def test_fixed_expense_ownership(api, other_api):
    fid = _fixed(api)
    mid = other_api.new_month()
    assert other_api.delete(f'/fixed_expenses/{fid}').status_code == 404
    assert other_api.put(f'/fixed_expenses/{fid}', RENT).status_code == 404
    assert _pay(other_api, fid, mid, 1).status_code == 404


def test_month_page_renders_fixed_label_safely(api):
    mid = api.new_month()
    _fixed(api)
    html = api.client.get(f'/month/{mid}').get_data(as_text=True)
    assert '<b>' not in html.split('fixedList')[1][:3000]
    assert 'data-label="Rent&#39;s &#34;flat&#34; &lt;b&gt;"' in html
    assert "openEditFixed(" not in html.split('<script>')[0]


def test_budget_alerts(api):
    mid = api.new_month()
    assert api.post('/set_budget', {'category': 'Σούπερ Μάρκετ', 'amount': 100}).get_json()['success']
    api.add(mid, amount=95)
    html = api.client.get(f'/month/{mid}').get_data(as_text=True)
    assert 'Σχεδόν στο όριο' in html
    api.add(mid, amount=10)
    assert 'Υπέρβαση budget' in api.client.get(f'/month/{mid}').get_data(as_text=True)


def test_budget_validation_and_reset(api, raw_db):
    assert api.post('/set_budget', {'category': 'Άγνωστη', 'amount': 1}).status_code == 400
    assert api.post('/set_budget', {'category': 'Σούπερ Μάρκετ', 'amount': 'inf'}).status_code == 400
    api.post('/set_budget', {'category': 'Σούπερ Μάρκετ', 'amount': 50})
    api.post('/set_budget', {'category': 'Σούπερ Μάρκετ', 'amount': 0})
    assert raw_db.execute("SELECT COUNT(*) FROM budgets").fetchone()[0] == 0
