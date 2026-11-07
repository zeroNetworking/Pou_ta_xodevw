"""An existing (pre-refresh) database must keep working after the upgrade."""
import sqlite3
from datetime import date

import conftest
from conftest import Api, register
from services import db as db_module


def test_old_database_is_migrated(tmp_path, monkeypatch):
    path = str(tmp_path / 'old.db')
    conn = sqlite3.connect(path)
    # fixed_payments as it existed before transaction_id was added
    conn.execute('''CREATE TABLE fixed_payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT, fixed_expense_id INTEGER NOT NULL,
        month_id INTEGER NOT NULL, paid INTEGER DEFAULT 0, paid_at TEXT,
        UNIQUE(fixed_expense_id, month_id))''')
    conn.commit(); conn.close()

    monkeypatch.setattr(db_module, 'DB_PATH', path)
    db_module.init_db()
    db_module.init_db()  # idempotent

    conn = sqlite3.connect(path)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(fixed_payments)")]
    assert 'transaction_id' in cols

    conftest.app_module.app.config.update(TESTING=True)
    c = conftest.app_module.app.test_client()
    register(c)
    api = Api(c)
    mid = api.new_month()
    fid = api.post('/fixed_expenses', {'label': 'ΔΕΗ', 'amount': 60,
                                       'category': 'Σπίτι & Λογαριασμοί'}).get_json()['id']
    # Simulate a payment made by the OLD code: transaction exists, no link stored
    conn.execute("""INSERT INTO transactions (month_id, category, type, amount, description, transaction_date)
                    VALUES (?, 'Σπίτι & Λογαριασμοί', 'expense', 60, '[Σταθερό] ΔΕΗ', ?)""",
                 (mid, date.today().isoformat()))
    conn.execute("INSERT INTO fixed_payments (fixed_expense_id, month_id, paid) VALUES (?,?,1)", (fid, mid))
    conn.commit(); conn.close()

    assert api.stats(mid)['total_expense'] == 60
    api.post('/fixed_payment', {'fixed_expense_id': fid, 'month_id': mid, 'paid': 0})
    assert api.stats(mid)['total_expense'] == 0
