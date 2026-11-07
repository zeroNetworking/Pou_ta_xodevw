"""
Fixed Expenses Service
Business logic for recurring monthly bills and their payment tracking.

Each paid fixed expense with an amount creates one expense transaction in
the month. The link is stored in fixed_payments.transaction_id, so:
  - marking "paid" twice never creates a duplicate transaction
  - marking "unpaid" removes exactly that transaction (not every lookalike)
  - editing the fixed expense amount later doesn't orphan old transactions
"""

import logging
from datetime import datetime
from .db import get_db
from .constants import EXPENSE_TREE
from .validation import safe_float, parse_flag, parse_int, clean_str
from .transactions import default_date_for_month

logger = logging.getLogger(__name__)

MAX_LABEL_LENGTH = 100
FALLBACK_CATEGORY = 'Διάφορα / Έκτακτα'


def _error(msg: str, status: int = 400) -> dict:
    return {'success': False, 'error': msg, 'status': status}


def _validate(data: dict) -> tuple[dict | None, dict | None]:
    label = clean_str(data.get('label'), MAX_LABEL_LENGTH)
    if label is None:
        return None, _error(f'Η περιγραφή δεν μπορεί να υπερβαίνει τους {MAX_LABEL_LENGTH} χαρακτήρες')
    if not label:
        return None, _error('Η περιγραφή δεν μπορεί να είναι κενή')

    raw_amount = data.get('amount', 0)
    amount = safe_float(raw_amount, default=-1.0)
    if amount < 0:
        return None, _error('Μη έγκυρο ποσό')

    category = clean_str(data.get('category'), 100)
    if category is None or (category and category not in EXPENSE_TREE):
        return None, _error('Μη έγκυρη κατηγορία')

    return {'label': label, 'amount': round(amount, 2), 'category': category}, None


def add_fixed_expense(user_id: int, data: dict) -> dict:
    """
    Creates a new recurring fixed expense definition.
    Returns {'success': True, 'id': new_id} or error dict.
    """
    values, err = _validate(data)
    if err:
        return err

    db     = get_db()
    cursor = db.cursor()
    cursor.execute(
        """INSERT INTO fixed_expenses (user_id, label, amount, category, sort_order)
           VALUES (?,?,?,?, (SELECT COALESCE(MAX(sort_order), 0) + 1
                               FROM fixed_expenses WHERE user_id=?))""",
        (user_id, values['label'], values['amount'], values['category'], user_id)
    )
    db.commit()
    new_id = cursor.lastrowid
    logger.info("User %s added fixed expense #%s: %s", user_id, new_id, values['label'])
    return {'success': True, 'id': new_id}


def delete_fixed_expense(user_id: int, fixed_expense_id: int) -> dict:
    """
    Deletes a fixed expense and all its payment records.
    Already-created transactions are kept: they are real money that was
    spent and belong to the month's history.
    """
    db     = get_db()
    cursor = db.cursor()
    # Verify ownership first — abort if this expense doesn't belong to the user
    cursor.execute(
        "SELECT id FROM fixed_expenses WHERE id=? AND user_id=?", (fixed_expense_id, user_id)
    )
    if not cursor.fetchone():
        return _error('Δεν βρέθηκε', 404)
    cursor.execute("DELETE FROM fixed_payments WHERE fixed_expense_id=?", (fixed_expense_id,))
    cursor.execute("DELETE FROM fixed_expenses WHERE id=?", (fixed_expense_id,))
    db.commit()
    logger.info("User %s deleted fixed expense #%s", user_id, fixed_expense_id)
    return {'success': True}


def edit_fixed_expense(user_id: int, fixed_expense_id: int, data: dict) -> dict:
    """
    Updates an existing fixed expense (label, amount, category).
    Affects future payments only; past transactions keep their amounts.
    """
    values, err = _validate(data)
    if err:
        return err

    db     = get_db()
    cursor = db.cursor()

    cursor.execute(
        "SELECT id FROM fixed_expenses WHERE id=? AND user_id=?", (fixed_expense_id, user_id)
    )
    if not cursor.fetchone():
        return _error('Δεν βρέθηκε', 404)

    cursor.execute(
        "UPDATE fixed_expenses SET label=?, amount=?, category=? WHERE id=?",
        (values['label'], values['amount'], values['category'], fixed_expense_id)
    )
    db.commit()
    logger.info("User %s edited fixed expense #%s: %s", user_id, fixed_expense_id, values['label'])
    return {'success': True}


def get_fixed_payment_status(user_id: int, month_id: int) -> tuple[list, dict]:
    """
    Returns (fixed_expenses, {fixed_expense_id: {'paid', 'paid_at'}}) for a
    month in two queries (instead of one query per fixed expense).
    """
    cursor = get_db().cursor()
    cursor.execute(
        "SELECT * FROM fixed_expenses WHERE user_id=? ORDER BY sort_order, id", (user_id,)
    )
    fixed_expenses = cursor.fetchall()
    cursor.execute(
        """SELECT fp.fixed_expense_id, fp.paid, fp.paid_at
           FROM fixed_payments fp JOIN fixed_expenses fe ON fe.id = fp.fixed_expense_id
           WHERE fp.month_id=? AND fe.user_id=?""",
        (month_id, user_id)
    )
    payments = {row['fixed_expense_id']: row for row in cursor.fetchall()}
    status = {}
    for fe in fixed_expenses:
        p = payments.get(fe['id'])
        status[fe['id']] = {
            'paid':    bool(p and p['paid']),
            'paid_at': p['paid_at'] if p else None,
        }
    return fixed_expenses, status


def toggle_fixed_payment(user_id: int, data: dict) -> dict:
    """
    Marks a fixed expense as paid or unpaid for a specific month.
    Idempotent: repeating the same request does not change anything.
    Only works on open months.
    """
    fixed_expense_id = parse_int(data.get('fixed_expense_id'))
    month_id         = parse_int(data.get('month_id'))
    if fixed_expense_id is None or month_id is None:
        return _error('Μη έγκυρα δεδομένα')
    mark_as_paid = parse_flag(data.get('paid', 1), default=1)

    db     = get_db()
    cursor = db.cursor()

    # Verify ownership of the fixed expense
    cursor.execute(
        "SELECT * FROM fixed_expenses WHERE id=? AND user_id=?", (fixed_expense_id, user_id)
    )
    fixed_expense = cursor.fetchone()
    if not fixed_expense:
        return _error('Το σταθερό έξοδο δεν βρέθηκε', 404)

    # Verify the target month belongs to this user and is open
    cursor.execute("SELECT * FROM months WHERE id=? AND user_id=?", (month_id, user_id))
    target_month = cursor.fetchone()
    if not target_month:
        return _error('Ο μήνας δεν βρέθηκε', 404)
    if target_month['is_closed']:
        return _error('Δεν μπορείς να αλλάξεις σταθερά έξοδα σε κλειστό μήνα', 403)

    cursor.execute(
        "SELECT * FROM fixed_payments WHERE fixed_expense_id=? AND month_id=?",
        (fixed_expense_id, month_id)
    )
    existing = cursor.fetchone()
    already_paid = bool(existing and existing['paid'])

    if bool(mark_as_paid) == already_paid:
        return {'success': True, 'unchanged': True}

    transaction_id = None
    if mark_as_paid:
        amount = fixed_expense['amount'] or 0
        if amount > 0:
            category = fixed_expense['category']
            if category not in EXPENSE_TREE:
                category = FALLBACK_CATEGORY
            cursor.execute(
                """INSERT INTO transactions
                   (month_id, category, subcategory, type, amount, description, transaction_date)
                   VALUES (?,?,?,?,?,?,?)""",
                (month_id, category, '', 'expense', amount,
                 f"[Σταθερό] {fixed_expense['label']}",
                 default_date_for_month(target_month['year'], target_month['month']).isoformat())
            )
            transaction_id = cursor.lastrowid
    else:
        linked_id = existing['transaction_id'] if existing else None
        if linked_id:
            cursor.execute(
                "DELETE FROM transactions WHERE id=? AND month_id=?", (linked_id, month_id)
            )
        elif existing and (fixed_expense['amount'] or 0) > 0:
            # Legacy payments (before transaction_id existed): remove ONE
            # matching auto-transaction instead of every lookalike.
            cursor.execute(
                """DELETE FROM transactions WHERE id = (
                       SELECT id FROM transactions
                       WHERE month_id=? AND description=? AND type='expense'
                       ORDER BY id DESC LIMIT 1)""",
                (month_id, f"[Σταθερό] {fixed_expense['label']}")
            )

    cursor.execute(
        """INSERT INTO fixed_payments (fixed_expense_id, month_id, paid, paid_at, transaction_id)
           VALUES (?,?,?,?,?)
           ON CONFLICT(fixed_expense_id, month_id)
           DO UPDATE SET paid=excluded.paid, paid_at=excluded.paid_at,
                         transaction_id=excluded.transaction_id""",
        (fixed_expense_id, month_id, mark_as_paid,
         datetime.now().isoformat() if mark_as_paid else None, transaction_id)
    )
    db.commit()
    logger.info("User %s toggled fixed payment fe=%s month=%s paid=%s",
                user_id, fixed_expense_id, month_id, mark_as_paid)
    return {'success': True}
