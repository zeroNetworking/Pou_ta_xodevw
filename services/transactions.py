"""
Transaction Service
Business logic for adding, editing, and deleting transactions.
Routes call these functions — no SQL lives in routes.
"""

import calendar
from datetime import date
import logging
from .db import get_db
from .constants import INCOME_CATEGORIES, EXPENSE_TREE
from .validation import (
    ALLOWED_TYPES, MAX_CATEGORY_LENGTH, MAX_DESCRIPTION_LENGTH,
    parse_amount, parse_flag, clean_str, parse_iso_date, parse_int,
)

logger = logging.getLogger(__name__)


def _error(msg: str, status: int = 400) -> dict:
    return {'success': False, 'error': msg, 'status': status}


def month_bounds(year: int, month: int) -> tuple[date, date]:
    """First and last calendar day of an accounting month."""
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def default_date_for_month(year: int, month: int) -> date:
    """Today if it falls inside the month, otherwise the closest boundary."""
    first, last = month_bounds(year, month)
    today = date.today()
    return min(max(today, first), last)


def _validate_fields(data: dict, month_row) -> tuple[dict | None, dict | None]:
    """
    Validates the user-editable fields of a transaction against the month
    it belongs to. Returns (clean_values, None) or (None, error_dict).
    """
    trans_type = data.get('type', 'expense')
    if trans_type not in ALLOWED_TYPES:
        return None, _error(f'Μη έγκυρος τύπος: {trans_type}')

    amount = parse_amount(data.get('amount'))
    if amount is None:
        return None, _error('Το ποσό πρέπει να είναι θετικός αριθμός')

    category = clean_str(data.get('category'), MAX_CATEGORY_LENGTH)
    if not category:
        return None, _error('Η κατηγορία είναι υποχρεωτική')

    subcategory = clean_str(data.get('subcategory'), MAX_CATEGORY_LENGTH)
    if subcategory is None:
        return None, _error('Μη έγκυρη υποκατηγορία')

    # Category must match the transaction type, otherwise income would show
    # up in expense charts (and vice versa).
    if trans_type == 'income':
        if category not in INCOME_CATEGORIES:
            return None, _error('Μη έγκυρη κατηγορία εσόδου')
        subcategory = ''
    else:
        if category not in EXPENSE_TREE:
            return None, _error('Μη έγκυρη κατηγορία εξόδου')
        if subcategory and subcategory not in EXPENSE_TREE[category]:
            return None, _error('Η υποκατηγορία δεν ανήκει στην κατηγορία')

    description = clean_str(data.get('description'), MAX_DESCRIPTION_LENGTH)
    if description is None:
        return None, _error(f'Η περιγραφή μπορεί να έχει έως {MAX_DESCRIPTION_LENGTH} χαρακτήρες')

    # Date must be a real date inside the month the transaction belongs to.
    # Otherwise the calendar view and per-day stats silently break.
    raw_date = data.get('date')
    if raw_date in (None, ''):
        trans_date = default_date_for_month(month_row['year'], month_row['month'])
    else:
        trans_date = parse_iso_date(raw_date)
        if trans_date is None:
            return None, _error('Μη έγκυρη ημερομηνία')
        first, last = month_bounds(month_row['year'], month_row['month'])
        if not (first <= trans_date <= last):
            return None, _error(
                f'Η ημερομηνία πρέπει να είναι μέσα στον μήνα '
                f'({first.isoformat()} – {last.isoformat()})'
            )

    return {
        'type':        trans_type,
        'amount':      amount,
        'category':    category,
        'subcategory': subcategory,
        'description': description,
        'date':        trans_date.isoformat(),
    }, None


def add_transaction(user_id: int, data: dict) -> dict:
    """
    Validates and inserts a new transaction into a month.
    Returns {'success': True, 'id': new_id} or {'success': False, 'error': '...', 'status': int}.
    """
    month_id = parse_int(data.get('month_id'))
    if month_id is None:
        return _error('Μη έγκυρος μήνας')
    is_late_entry = parse_flag(data.get('late_entry', 0))

    db     = get_db()
    cursor = db.cursor()

    # Verify the target month belongs to this user
    cursor.execute("SELECT * FROM months WHERE id=? AND user_id=?", (month_id, user_id))
    month = cursor.fetchone()
    if not month:
        return _error('Ο μήνας δεν βρέθηκε', 404)

    # Closed months reject direct transactions unless it's a late entry;
    # late entries only make sense for closed months.
    if month['is_closed'] and not is_late_entry:
        return _error('Μη επεξεργάσιμος μήνας', 403)
    if is_late_entry and not month['is_closed']:
        return _error('Καθυστερημένη καταχώρηση επιτρέπεται μόνο σε κλειστό μήνα')

    values, err = _validate_fields(data, month)
    if err:
        return err

    late_note = ''
    if is_late_entry:
        late_note = clean_str(data.get('late_entry_note'), MAX_DESCRIPTION_LENGTH)
        if late_note is None:
            return _error('Μη έγκυρη σημείωση')

    cursor.execute(
        """INSERT INTO transactions
           (month_id, category, subcategory, type, amount, description,
            transaction_date, late_entry, late_entry_note)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            month_id, values['category'], values['subcategory'], values['type'],
            values['amount'], values['description'], values['date'],
            is_late_entry, late_note,
        )
    )
    db.commit()
    new_id = cursor.lastrowid
    logger.info("User %s added transaction #%s: %.2f€ %s / %s",
                user_id, new_id, values['amount'], values['type'], values['category'])
    return {'success': True, 'id': new_id}


def edit_transaction(user_id: int, transaction_id: int, data: dict) -> dict:
    """
    Updates an existing transaction. Verifies ownership via JOIN.
    Returns {'success': True} or {'success': False, 'error': '...', 'status': int}.
    """
    db     = get_db()
    cursor = db.cursor()

    # Ownership check via JOIN: transaction → month → user
    cursor.execute(
        """SELECT t.id, m.is_closed, m.year, m.month
           FROM transactions t JOIN months m ON t.month_id = m.id
           WHERE t.id=? AND m.user_id=?""",
        (transaction_id, user_id)
    )
    row = cursor.fetchone()
    if not row:
        logger.warning("User %s tried to edit transaction %s they don't own", user_id, transaction_id)
        return _error('Δεν βρέθηκε', 404)

    # Prevent editing transactions in closed months
    if row['is_closed']:
        return _error('Δεν μπορείς να επεξεργαστείς κίνηση σε κλειστό μήνα', 403)

    values, err = _validate_fields(data, row)
    if err:
        return err

    cursor.execute(
        """UPDATE transactions
           SET category=?, subcategory=?, type=?, amount=?, description=?, transaction_date=?
           WHERE id=?""",
        (
            values['category'], values['subcategory'], values['type'],
            values['amount'], values['description'], values['date'],
            transaction_id,
        )
    )
    db.commit()
    logger.info("User %s edited transaction #%s", user_id, transaction_id)
    return {'success': True}


def delete_transaction(user_id: int, transaction_id: int) -> dict:
    """
    Deletes a transaction after verifying ownership.
    If the transaction was auto-created by a fixed-expense payment, that
    payment is marked unpaid so the two never get out of sync.
    """
    db     = get_db()
    cursor = db.cursor()

    cursor.execute(
        """SELECT t.id, m.is_closed FROM transactions t JOIN months m ON t.month_id = m.id
           WHERE t.id=? AND m.user_id=?""",
        (transaction_id, user_id)
    )
    row = cursor.fetchone()
    if not row:
        logger.warning("User %s tried to delete transaction %s they don't own", user_id, transaction_id)
        return _error('Δεν βρέθηκε', 404)

    # Prevent deleting transactions from closed months
    if row['is_closed']:
        return _error('Δεν μπορείς να διαγράψεις κίνηση από κλειστό μήνα', 403)

    cursor.execute(
        "UPDATE fixed_payments SET paid=0, paid_at=NULL, transaction_id=NULL WHERE transaction_id=?",
        (transaction_id,)
    )
    cursor.execute("DELETE FROM transactions WHERE id=?", (transaction_id,))
    db.commit()
    logger.info("User %s deleted transaction #%s", user_id, transaction_id)
    return {'success': True}
