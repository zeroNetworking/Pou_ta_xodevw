"""
Validation Helpers
Input validation used across multiple services and routes.

Every helper here is defensive: JSON bodies can contain any type (numbers,
strings, lists, null), so nothing assumes the caller sent what the UI sends.
"""

import math
import re
from datetime import date

# Allowed transaction types — used for whitelist validation
ALLOWED_TYPES = {'income', 'expense'}

# Upper bound for any single monetary value. Protects charts/PDF from
# absurd numbers and catches typos like an extra few zeros.
MAX_AMOUNT = 10_000_000

# Text length limits
MAX_CATEGORY_LENGTH    = 100
MAX_DESCRIPTION_LENGTH = 500


def safe_float(value, default: float = 0.0) -> float:
    """
    Converts a value to a finite, non-negative float (<= MAX_AMOUNT).
    Returns default on failure. Rejects NaN / Infinity, which float()
    happily accepts from strings like 'nan' or 'inf'.
    """
    if isinstance(value, bool):
        return default
    try:
        result = float(value)
    except (ValueError, TypeError):
        return default
    if not math.isfinite(result) or result < 0 or result > MAX_AMOUNT:
        return default
    return result


def parse_amount(value):
    """Returns a positive amount rounded to cents, or None if invalid."""
    amount = safe_float(value, default=-1.0)
    if amount <= 0:
        return None
    return round(amount, 2)


def parse_flag(value, default: int = 0) -> int:
    """
    Parses a boolean-ish flag (1/0, true/false, '1'/'0') into 0 or 1.
    Never raises — unknown values fall back to `default`.
    """
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)) and value in (0, 1):
        return int(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ('1', 'true', 'yes', 'on'):
            return 1
        if v in ('0', 'false', 'no', 'off', ''):
            return 0
    return default


def clean_str(value, max_len: int) -> str | None:
    """
    Returns a stripped string, '' for missing values, or None if the value
    is not a string or exceeds max_len.
    """
    if value is None:
        return ''
    if not isinstance(value, str):
        return None
    value = value.strip()
    if len(value) > max_len:
        return None
    return value


def parse_iso_date(value) -> date | None:
    """Parses a YYYY-MM-DD string into a date. Returns None if invalid."""
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def parse_int(value) -> int | None:
    """Parses an int ID from JSON (int or numeric string). None if invalid."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def is_valid_password(password: str) -> bool:
    """Min 8 chars, 1 uppercase, 1 digit, 1 symbol."""
    return (
        len(password) >= 8
        and bool(re.search(r'[A-Z]', password))
        and bool(re.search(r'[0-9]', password))
        and bool(re.search(r'[^A-Za-z0-9]', password))
    )


def is_valid_username(username: str) -> bool:
    """8–12 chars, letters/digits/underscore only."""
    return (
        8 <= len(username) <= 12
        and bool(re.match(r'^[A-Za-z0-9_]+$', username))
    )


# Recovery answer rules: prevent trivially weak answers (empty, "a", "1234").
# We hash the answer like a password, so "low entropy = brute-forceable".
MIN_RECOVERY_ANSWER_LENGTH = 3
MAX_RECOVERY_ANSWER_LENGTH = 100


def is_valid_recovery_answer(answer: str) -> bool:
    """
    Recovery answer: 3–100 chars after stripping whitespace.
    Short enough to remember, long enough to resist trivial guessing.
    """
    cleaned = (answer or '').strip()
    return MIN_RECOVERY_ANSWER_LENGTH <= len(cleaned) <= MAX_RECOVERY_ANSWER_LENGTH


def normalize_recovery_answer(answer: str) -> str:
    """
    Canonicalize the answer before hashing so that 'Rex', ' rex ', and
    'REX' all match. We lowercase + strip — same approach used by major
    providers for security questions.
    """
    return (answer or '').strip().lower()
